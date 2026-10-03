"""Geocoding, distance and relative-date helpers.

Distance drives realistic transport-mode and budget guidance instead of
asking the same generic questions for every route, regardless of whether
it's a 300 km hop or an intercontinental trip.
"""
import calendar
import math
import os
import re
from datetime import date, timedelta

import requests

from .utils import load_dotenv, mark_api_exception, mark_api_response, API_HEALTH

load_dotenv()

OPENCAGE_KEY = os.getenv("OPENCAGE_API_KEY", "").strip()

FLIGHT_ONLY_THRESHOLD_KM = 1000

_GEOCODE_CACHE = {}

def geocode(place):
    if not OPENCAGE_KEY or not place:
        if not OPENCAGE_KEY:
            API_HEALTH["opencage"] = False
        return None
    key = str(place).strip().lower()
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    try:
        response = requests.get("https://api.opencagedata.com/geocode/v1/json", params={"q": place, "key": OPENCAGE_KEY, "limit": 1}, timeout=12)
        mark_api_response("opencage", response)
        response.raise_for_status()
        results = response.json().get("results", [])
        if results:
            geometry = results[0].get("geometry", {})
            components = results[0].get("components", {})
            short_name = components.get("city") or components.get("town") or components.get("village") or components.get("state") or components.get("country")
            short_name = short_name or str(place).title()
            country = components.get("country")
            value = {
                "lat": geometry.get("lat"), "lng": geometry.get("lng"),
                "formatted": results[0].get("formatted", place),
                "short_name": short_name,
                "short_label": f"{short_name}, {country}" if country and country != short_name else short_name,
                "country": country,
                "is_place": bool(components.get("city") or components.get("town") or components.get("village") or components.get("county") or components.get("state") or components.get("country")),
            }
            _GEOCODE_CACHE[key] = value
            return value
    except (requests.RequestException, ValueError, TypeError) as error:
        mark_api_exception("opencage", error)
        return None
    return None

def haversine_km(lat1, lng1, lat2, lng2):
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def route_distance_km(origin_place, destination_place):
    if not origin_place or not destination_place:
        return None
    if origin_place.get("lat") is None or destination_place.get("lat") is None:
        return None
    return round(haversine_km(origin_place["lat"], origin_place["lng"], destination_place["lat"], destination_place["lng"]), 1)

def feasible_transport_modes(distance_km):
    if distance_km and distance_km > FLIGHT_ONLY_THRESHOLD_KM:
        return ["flight"]
    return ["train", "flight", "bus", "car"]

def add_months(base, months):
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def resolve_relative_date(text):
    """Resolve simple relative phrases ("next week", "in 3 days", ...) to a
    concrete date relative to today. Returns None if nothing relative matched,
    so callers can fall through to strict ISO-date parsing."""
    t = text.strip().lower()
    today = date.today()
    if "today" in t:
        return today
    if "tomorrow" in t:
        return today + timedelta(days=1)
    match = re.search(r"in\s+(\d+)\s+day", t)
    if match:
        return today + timedelta(days=int(match.group(1)))
    match = re.search(r"in\s+(\d+)\s+week", t)
    if match:
        return today + timedelta(weeks=int(match.group(1)))
    match = re.search(r"in\s+(\d+)\s+month", t)
    if match:
        return add_months(today, int(match.group(1)))
    if "next week" in t:
        return today + timedelta(weeks=1)
    if "next month" in t:
        return add_months(today, 1)
    return None
