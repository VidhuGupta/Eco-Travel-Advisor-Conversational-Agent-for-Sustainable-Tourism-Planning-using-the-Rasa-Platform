"""Live external data providers: flights, carbon estimates, events/activities,
and real driving-route distance. Every call degrades to an empty/unavailable
result on failure rather than raising, so a provider outage never breaks a
turn - the caller decides what an empty result means (see planning.py)."""
import os

import requests

from .utils import load_dotenv, mark_api_exception, mark_api_response, API_HEALTH
from .geo import geocode, haversine_km

load_dotenv()

TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "").strip()
CLIMATIQ_KEY = os.getenv("CLIMATIQ_API_KEY", "").strip()
TICKETMASTER_KEY = os.getenv("TICKETMASTER_API_KEY", "").strip()
ORS_KEY = os.getenv("ORS_API_KEY", "").strip()

_ECO_CONTACT = os.getenv("ECO_CONTACT", "").strip()
APP_USER_AGENT = f"vidhu-rasa-eco-travel-advisor/1.0 ({_ECO_CONTACT})" if _ECO_CONTACT else "vidhu-rasa-eco-travel-advisor/1.0"

TRANSPORT_TO_CLIMATIQ_MODE = {"train": "rail", "car": "car", "flight": "air"}

TRANSPORT_TO_ORS_PROFILE = {"car": "driving-car", "bus": "driving-hgv"}

def resolve_iata(place):
    if not place:
        return None
    term = place.split(",")[0].strip()
    try:
        response = requests.get("https://autocomplete.travelpayouts.com/places2", params={"term": term, "locale": "en", "types[]": "city,airport"}, timeout=8)
        response.raise_for_status()
        term_lower = term.lower()
        for item in response.json():
            code = item.get("code") or item.get("iata") or item.get("iata_code")
            if not (code and len(code) == 3):
                continue
            name = f"{item.get('name', '')} {item.get('city_name', '')} {item.get('main_airport_name', '')}".lower()
            if term_lower in name:
                return code.upper()
    except (requests.RequestException, ValueError, TypeError):
        pass
    return None

def live_flights(origin, destination, start, end, currency):
    if not TRAVELPAYOUTS_TOKEN:
        API_HEALTH["travelpayouts_fares"] = False
        return []
    from_code, to_code = resolve_iata(origin), resolve_iata(destination)
    if not (from_code and to_code):
        return []
    items = []
    try:
        response = requests.get(
            "https://api.travelpayouts.com/v2/prices/latest",
            params={"origin": from_code, "destination": to_code, "currency": currency.lower(), "limit": 15, "sorting": "price"},
            headers={"X-Access-Token": TRAVELPAYOUTS_TOKEN}, timeout=15,
        )
        mark_api_response("travelpayouts_fares", response)
        response.raise_for_status()
        for fare in response.json().get("data", [])[:15]:
            value = fare.get("value")
            depart = fare.get("depart_date", "")
            items.append({
                "id": f"tp-{from_code}-{to_code}-{depart}-{len(items)}",
                "category": "Transport", "name": f"{from_code} to {to_code} fare, via {fare.get('gate', 'a booking partner')}",
                "description": f"Recently observed fare for {depart or 'a nearby date'}{' - ' + fare.get('return_date') if fare.get('return_date') else ''}; not a live quote for your exact dates or a confirmed booking.",
                "mode": "flight", "price": float(value) if value is not None else None, "currency": currency,
                "depart_date": depart or None,
                "source": "Travelpayouts cached data", "source_url": "https://www.aviasales.com/",
            })
    except (requests.RequestException, ValueError, TypeError) as error:
        mark_api_exception("travelpayouts_fares", error)
    return items

_TRANSITOUS_LEG_MODE = {
    "RAIL": "train", "HIGHSPEED_RAIL": "train", "LONG_DISTANCE": "train", "REGIONAL_RAIL": "train",
    "REGIONAL_FAST_RAIL": "train", "NIGHT_RAIL": "train", "SUBURBAN": "train", "SUBWAY": "train",
    "METRO": "train", "TRAM": "train", "FUNICULAR": "train",
    "BUS": "bus", "COACH": "bus",
    "FERRY": "ferry",
}

def live_transit(origin, destination, start):
    """Real train/bus/ferry itineraries between two places, from Transitous."""
    origin_place, destination_place = geocode(origin), geocode(destination)
    if not origin_place or not destination_place or origin_place.get("lat") is None or destination_place.get("lat") is None:
        API_HEALTH["transitous"] = False
        return []
    depart_date = start if start and start != "Flexible" else None
    time_param = f"{depart_date}T08:00:00Z" if depart_date else None
    params = {
        "fromPlace": f"{origin_place['lat']},{origin_place['lng']}",
        "toPlace": f"{destination_place['lat']},{destination_place['lng']}",
        "numItineraries": 5,
    }
    if time_param:
        params["time"] = time_param
    try:
        response = requests.get("https://api.transitous.org/api/v1/plan", params=params, headers={"User-Agent": APP_USER_AGENT}, timeout=15)
        mark_api_response("transitous", response)
        response.raise_for_status()
        itineraries = response.json().get("itineraries") or []
        items = []
        for itinerary in itineraries:
            legs = [leg for leg in (itinerary.get("legs") or []) if leg.get("mode") != "WALK"]
            if not legs:
                continue
            leg_modes = {_TRANSITOUS_LEG_MODE.get(leg.get("mode", ""), "other") for leg in legs}
            if "other" in leg_modes:
                continue
            main_mode = "train" if "train" in leg_modes else ("bus" if "bus" in leg_modes else "ferry")
            transfers = itinerary.get("transfers", max(0, len(legs) - 1))
            duration_min = round((itinerary.get("duration") or 0) / 60)
            route_names = ", ".join(dict.fromkeys(leg.get("routeShortName") or leg.get("mode", "").title() for leg in legs))
            hours, minutes = divmod(duration_min, 60)
            duration_label = f"{hours}h {minutes:02d}m" if hours else f"{minutes} min"
            transfer_label = "direct" if transfers == 0 else f"{transfers} transfer{'s' if transfers != 1 else ''}"
            items.append({
                "id": f"transitous-{main_mode}-{len(items)}",
                "category": "Transport", "name": f"{main_mode.title()} via {route_names}" if route_names else main_mode.title(),
                "description": f"{duration_label}, {transfer_label}. Departs {(itinerary.get('startTime') or 'a scheduled time')[:16].replace('T', ' ')}.",
                "mode": main_mode, "price": None, "currency": None,
                "depart_date": (itinerary.get("startTime") or "")[:10] or None,
                "source": "Transitous", "source_url": None,
            })
        return items[:6]
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as error:
        mark_api_exception("transitous", error)
        return []

_FLIGHT_SHORT_HAUL_FACTOR = "passenger_flight-route_type_international-aircraft_type_na-distance_short_haul_lt_3700km-class_na-rf_included-distance_uplift_included"
_FLIGHT_LONG_HAUL_FACTOR = "passenger_flight-route_type_international-aircraft_type_na-distance_long_haul_gt_3700km-class_na-rf_included"
_RAIL_FACTOR = "passenger_train-route_type_national_rail-fuel_source_na"
_CAR_FACTOR = "passenger_vehicle-vehicle_type_car-fuel_source_na-engine_size_na-vehicle_age_na-vehicle_weight_na"

def _carbon_factor_id(mode, distance_km):
    if mode == "air":
        return _FLIGHT_LONG_HAUL_FACTOR if distance_km and distance_km > 3700 else _FLIGHT_SHORT_HAUL_FACTOR
    if mode == "rail":
        return _RAIL_FACTOR
    if mode == "car":
        return _CAR_FACTOR
    return None

_FALLBACK_FACTOR_PER_KM = {"air": 0.150, "rail": 0.035, "car": 0.171}

def live_carbon(mode, distance_km):
    if not distance_km:
        return None
    if not CLIMATIQ_KEY:
        API_HEALTH["climatiq"] = False
        return _fallback_carbon(mode, distance_km)
    activity_id = _carbon_factor_id(mode, distance_km)
    if not activity_id:
        return None
    payload = {
        "emission_factor": {"activity_id": activity_id, "data_version": "^0"},
        "parameters": {"passengers": 1, "distance": distance_km, "distance_unit": "km"},
    }
    try:
        response = requests.post("https://api.climatiq.io/data/v1/estimate", json=payload, headers={"Authorization": f"Bearer {CLIMATIQ_KEY}", "Content-Type": "application/json"}, timeout=18)
        mark_api_response("climatiq", response)
        response.raise_for_status()
        data = response.json()
        value = data.get("co2e")
        return {"mode": mode, "label": mode.title(), "emissions_kg": round(float(value), 2) if value is not None else None, "unit": data.get("co2e_unit", "kg"), "source": "Climatiq"}
    except (requests.RequestException, ValueError, TypeError) as error:
        mark_api_exception("climatiq", error)
        return _fallback_carbon(mode, distance_km)

def _fallback_carbon(mode, distance_km):
    factor = _FALLBACK_FACTOR_PER_KM.get(mode)
    if factor is None:
        return None
    return {
        "mode": mode, "label": mode.title(), "emissions_kg": round(distance_km * factor, 2), "unit": "kg",
        "source": "Estimated (offline fallback factor, Climatiq unavailable)",
    }

def live_activities(destination, start, end):
    """Real events/experiences at the destination during the trip window."""
    if not TICKETMASTER_KEY or not destination:
        API_HEALTH["ticketmaster"] = False
        return []
    city = destination.split(",")[0].strip()
    params = {"apikey": TICKETMASTER_KEY, "city": city, "size": 15, "sort": "date,asc"}
    if start and start != "Flexible":
        params["startDateTime"] = f"{start}T00:00:00Z"
    if end and end != "Flexible":
        params["endDateTime"] = f"{end}T23:59:59Z"
    try:
        response = requests.get("https://app.ticketmaster.com/discovery/v2/events.json", params=params, timeout=15)
        mark_api_response("ticketmaster", response)
        response.raise_for_status()
        events = response.json().get("_embedded", {}).get("events", [])
        items = []
        seen = set()
        for event in events:
            venue = ((event.get("_embedded") or {}).get("venues") or [{}])[0]
            venue_name = venue.get("name", destination)
            start_info = event.get("dates", {}).get("start", {})
            event_date = start_info.get("localDate", "a date to be confirmed")
            event_time = start_info.get("localTime")
            dedupe_key = (event.get("name"), venue_name, event_date, event_time)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            price_ranges = event.get("priceRanges") or [{}]
            price_min, price_max = price_ranges[0].get("min"), price_ranges[0].get("max")
            classification = ((event.get("classifications") or [{}])[0].get("segment") or {}).get("name")
            time_label = f" at {event_time[:5]}" if event_time else ""
            price_label = (
                f"{price_ranges[0].get('currency', '')} {price_min:.0f}-{price_max:.0f}" if price_min is not None and price_max is not None and price_min != price_max
                else f"{price_ranges[0].get('currency', '')} {price_min:.0f}" if price_min is not None
                else None
            )
            items.append({
                "id": event.get("id"), "category": "Activity", "name": event.get("name", "Event"),
                "description": f"{classification + ' - ' if classification else ''}{venue_name} on {event_date}{time_label}.",
                "price": float(price_min) if price_min is not None else None, "currency": price_ranges[0].get("currency"),
                "price_label": price_label,
                "source": "Ticketmaster", "source_url": event.get("url"),
            })
            if len(items) >= 5:
                break
        return items
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as error:
        mark_api_exception("ticketmaster", error)
        return []

def live_driving_route(origin_place, destination_place, profile="driving-car"):
    """Real road distance/duration from OpenRouteService, for the car/bus
    recommendation cards. Falls back silently (returns None) for routes that
    aren't drivable (e.g. separated by ocean) - the caller still has the
    straight-line route_distance_km for feasibility decisions."""
    if not ORS_KEY or not origin_place or not destination_place:
        if not ORS_KEY:
            API_HEALTH["ors"] = False
        return None
    if origin_place.get("lat") is None or destination_place.get("lat") is None:
        return None
    coordinates = [[origin_place["lng"], origin_place["lat"]], [destination_place["lng"], destination_place["lat"]]]
    try:
        response = requests.post(
            f"https://api.openrouteservice.org/v2/directions/{profile}",
            json={"coordinates": coordinates}, headers={"Authorization": ORS_KEY, "Content-Type": "application/json"}, timeout=15,
        )
        mark_api_response("ors", response)
        response.raise_for_status()
        summary = response.json()["routes"][0]["summary"]
        return {"distance_km": round(summary["distance"] / 1000, 1), "duration_hours": round(summary["duration"] / 3600, 1), "source": "OpenRouteService"}
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as error:
        mark_api_exception("ors", error)
        return None

def live_stays(destination):
    """Real named places to stay near the destination, from OpenStreetMap
    (Overpass) - free, no API key. There is no connected hotel-booking
    provider (no price/availability), but showing real nearby places with
    a name, distance and map link is still a genuine improvement over
    showing nothing at all for accommodation."""
    place = geocode(destination)
    if not place or place.get("lat") is None:
        API_HEALTH["overpass"] = False
        return []
    lat, lng = place["lat"], place["lng"]
    query = (
        f'[out:json][timeout:20];'
        f'(node["tourism"="hotel"](around:2000,{lat},{lng});'
        f'way["tourism"="hotel"](around:2000,{lat},{lng});'
        f'relation["tourism"="hotel"](around:2000,{lat},{lng}););'
        f'out center 15;'
    )
    attempts = 2
    response = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                "https://overpass-api.de/api/interpreter", data=query,
                headers={"User-Agent": APP_USER_AGENT}, timeout=25,
            )
            mark_api_response("overpass", response)
            response.raise_for_status()
            break
        except (requests.RequestException, ValueError, TypeError) as error:
            mark_api_exception("overpass", error)
            response = None
    if response is None:
        return []
    try:
        elements = response.json().get("elements", [])
        items = []
        for element in elements:
            tags = element.get("tags", {})
            name = tags.get("name")
            center = element.get("center") or {}
            elem_lat, elem_lng = element.get("lat", center.get("lat")), element.get("lon", center.get("lon"))
            if not name or elem_lat is None:
                continue
            distance_km = round(haversine_km(lat, lng, elem_lat, elem_lng), 1)
            facts = [f"{distance_km} km from the centre"]
            if tags.get("wheelchair") == "yes":
                facts.append("Wheelchair accessible")
            if tags.get("stars"):
                facts.append(f"{tags['stars']}-star")
            items.append({
                "id": f"osm-{element.get('id')}", "category": "Stay", "name": name,
                "description": ", ".join(facts) + ".",
                "price": None, "currency": None,
                "source": "OpenStreetMap", "source_url": tags.get("website") or f"https://www.openstreetmap.org/node/{element.get('id')}",
                "distance_km": distance_km,
            })
        items.sort(key=lambda item: item["distance_km"])
        return items[:6]
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as error:
        mark_api_exception("overpass", error)
        return []

def nearby_sights(destination):
    """Real nearby landmarks/points of interest from Wikipedia's geosearch -
    free, no API key. Fills the "things to see" gap the same way live_stays
    fills accommodation: no ticketed-event provider covers general sights,
    but Wikipedia's own location index does."""
    place = geocode(destination)
    if not place or place.get("lat") is None:
        API_HEALTH["wikipedia"] = False
        return []
    lat, lng = place["lat"], place["lng"]
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "generator": "geosearch", "ggscoord": f"{lat}|{lng}",
                "ggsradius": 3000, "ggslimit": 8, "prop": "pageimages|extracts|coordinates",
                "exintro": 1, "explaintext": 1, "exchars": 200, "piprop": "thumbnail", "pithumbsize": 300,
                "format": "json",
            },
            headers={"User-Agent": APP_USER_AGENT}, timeout=15,
        )
        mark_api_response("wikipedia", response)
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages", {})
        items = []
        for page in pages.values():
            coords = (page.get("coordinates") or [{}])[0]
            distance_km = round(haversine_km(lat, lng, coords.get("lat", lat), coords.get("lon", lng)), 1) if coords else None
            title = page.get("title") or "Landmark"
            items.append({
                "id": f"wiki-{page.get('pageid')}", "category": "Sight", "name": title,
                "description": (page.get("extract") or "")[:180],
                "price": None, "currency": None,
                "source": "Wikipedia", "source_url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                "image": (page.get("thumbnail") or {}).get("source"),
                "distance_km": distance_km,
            })
        items.sort(key=lambda item: item["distance_km"] if item["distance_km"] is not None else 999)
        return items[:6]
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as error:
        mark_api_exception("wikipedia", error)
        return []
