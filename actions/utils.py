"""Shared helpers used across the action modules: env loading and slot access."""
import os

from rasa_sdk import Tracker

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path=".env"):
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), path) if not os.path.isabs(path) else path
        try:
            with open(env_path, encoding="utf-8") as env_file:
                for line in env_file:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    name, value = name.strip(), value.strip().strip("\"'")
                    if name and name not in os.environ:
                        os.environ[name] = value
        except OSError:
            return False
        return True

load_dotenv()

def get_slot(tracker: Tracker, name: str, default=None):
    value = tracker.get_slot(name)
    return default if value is None else value

NON_SLOT_INTENTS = {
    "session_greeting", "session_closing", "capability_overview",
    "unsupported_topic", "request_specialist",
}

API_HEALTH = {
    "travelpayouts_fares": None, "opencage": None, "climatiq": None,
    "ticketmaster": None, "ors": None, "overpass": None, "wikipedia": None,
    "transitous": None,
}

def mark_api_response(provider, response):
    status = response.status_code
    available = not (status in (401, 403, 429) or status >= 500)
    API_HEALTH[provider] = API_HEALTH.get(provider) is True or available

def mark_api_exception(provider, error):
    response = getattr(error, "response", None)
    if response is not None:
        mark_api_response(provider, response)
    elif API_HEALTH.get(provider) is not True:
        API_HEALTH[provider] = False

def public_api_status():
    labels = {
        "travelpayouts_fares": "Travelpayouts fares", "opencage": "OpenCage",
        "climatiq": "Climatiq", "ticketmaster": "Ticketmaster", "ors": "OpenRouteService",
        "overpass": "OpenStreetMap", "wikipedia": "Wikipedia", "transitous": "Transitous",
    }
    return {labels.get(name, name): ("available" if value is True else "unavailable" if value is False else "not checked") for name, value in API_HEALTH.items()}
