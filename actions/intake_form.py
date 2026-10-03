"""The consultation_form: starting a consultation, extracting/validating each
slot, and the ask-only actions that only ever speak the single question for
their step (so a form submission never produces more than one bot message
per turn)."""
import re
from datetime import date
from typing import Any, Text, Dict, List

from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import FollowupAction, SlotSet

from .utils import get_slot, NON_SLOT_INTENTS
from .geo import geocode, route_distance_km, feasible_transport_modes, resolve_relative_date, OPENCAGE_KEY

PLACE_ANSWER_INTENTS = {"start_consultation", "provide_destination", "select_destination", "nlu_fallback"}

_PLACE_FILLER_WORDS = {
    "plan", "planning", "book", "booking", "trip", "journey", "consultation",
    "getaway", "vacation", "holiday", "travel", "travelling", "traveling",
    "go", "going", "visit", "visiting", "to", "towards", "for", "at", "in",
    "i", "want", "wanna", "would", "like", "help", "me", "us", "we",
    "let's", "lets", "please", "can", "could", "start", "create",
}

_PLACE_BARE_ARTICLES = {"a", "an", "the"}

def _extract_place_phrase(text):
    text = (text or "").strip()
    words = re.findall(r"\S+", text)
    kept = [word for word in words if word.strip(".,!?").lower() not in _PLACE_FILLER_WORDS]
    candidate = " ".join(kept).strip(" .,!?")
    if not candidate:
        return None
    if candidate.lower() in _PLACE_BARE_ARTICLES:
        return None
    return candidate

_TRAILING_PHRASE_RE = r"\s+(?:next|this|coming|tomorrow|today|please|for|on|by|around|starting|from)\b|[.,!?]|$"
_FROM_TO_RE = re.compile(
    rf"\bfrom\s+(?P<origin>.+?)\s+to\s+(?P<destination>.+?)(?={_TRAILING_PHRASE_RE})",
    re.IGNORECASE,
)

def _from_to_places(text):
    match = _FROM_TO_RE.search(text or "")
    if not match:
        return None, None
    origin = match.group("origin").strip(" .,!?")
    destination = match.group("destination").strip(" .,!?")
    if re.match(r"^\d", origin) or re.match(r"^\d", destination):
        return None, None
    return (origin or None), (destination or None)

class ActionStartConsultation(Action):

    def name(self) -> Text:
        return "action_start_consultation"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        already_active = bool(tracker.active_loop and tracker.active_loop.get("name") == "consultation_form")

        if not already_active:
            dispatcher.utter_message(
                text=(
                    "Let's start planning your trip. "
                    "I will collect the destination, travel dates, "
                    "budget and preferences one step at a time."
                )
            )

        events = [] if already_active else [
            SlotSet(slot_name, None)
            for slot_name in (
                "destination", "travel_start", "travel_end", "budget",
                "origin", "currency", "carbon_estimate_preference",
                "sustainability_level", "transport_preference",
                "accommodation_preference", "carbon_results",
                "recommendation_results", "handover_context", "handover_reason",
                "route_distance_km", "pending_date_phrase",
            )
        ] + ([] if already_active else [SlotSet("confusion_count", 0), SlotSet("awaiting_handover_confirm", False), SlotSet("awaiting_recap_confirm", False)])

        latest = tracker.latest_message or {}
        hint = next((entity.get("value") for entity in latest.get("entities", []) if entity.get("entity") == "travel_start"), None)
        if hint:
            if "flexible" in hint.lower():
                events += [SlotSet("travel_start", "Flexible"), SlotSet("travel_end", "Flexible")]
            else:
                events.append(SlotSet("pending_date_phrase", hint))

        for slot_name in ("sustainability_level", "transport_preference", "accommodation_preference"):
            value = next((entity.get("value") for entity in latest.get("entities", []) if entity.get("entity") == slot_name), None)
            if value:
                events.append(SlotSet(slot_name, value))
        return events

class ValidateConsultationForm(FormValidationAction):
    """Validate and normalize values collected by the consultation form."""

    def name(self) -> Text:
        return "validate_consultation_form"

    def extract_origin(self, dispatcher, tracker, domain):
        if tracker.get_slot("origin"):
            return {}
        latest = tracker.latest_message or {}
        from_place, _ = _from_to_places(latest.get("text") or "")
        if from_place:
            return {"origin": from_place}
        for entity in latest.get("entities", []):
            if entity.get("entity") == "origin":
                return {"origin": entity.get("value")}
        if tracker.get_slot("destination") and tracker.get_slot("requested_slot") == "origin":
            for entity in latest.get("entities", []):
                if entity.get("entity") == "destination":
                    return {"origin": entity.get("value")}
        if tracker.get_slot("requested_slot") == "origin" and latest.get("intent", {}).get("name") in PLACE_ANSWER_INTENTS:
            text = (latest.get("text") or "").strip()
            if text and not text.startswith("/"):
                phrase = _extract_place_phrase(text)
                if phrase:
                    return {"origin": phrase}
        return {}

    def extract_destination(self, dispatcher, tracker, domain):
        if tracker.get_slot("destination"):
            return {}
        latest = tracker.latest_message or {}
        _, to_place = _from_to_places(latest.get("text") or "")
        if to_place:
            return {"destination": to_place}
        for entity in latest.get("entities", []):
            if entity.get("entity") == "destination":
                return {"destination": entity.get("value")}
        if tracker.get_slot("requested_slot") in ("destination", None) and latest.get("intent", {}).get("name") in PLACE_ANSWER_INTENTS:
            text = (latest.get("text") or "").strip()
            if text and not text.startswith("/"):
                phrase = _extract_place_phrase(text)
                if phrase:
                    return {"destination": phrase}
        return {}

    def _entity_value(self, latest, entity_name):
        for entity in latest.get("entities", []):
            if entity.get("entity") == entity_name:
                return entity.get("value")
        return None

    def _structured_entity_value(self, latest, entity_name):
        for entity in latest.get("entities", []):
            if entity.get("entity") == entity_name and entity.get("extractor") == "RegexMessageHandler":
                return entity.get("value")
        return None

    def extract_budget(self, dispatcher, tracker, domain):
        if tracker.get_slot("budget"):
            return {}
        latest = tracker.latest_message or {}
        value = self._entity_value(latest, "budget")
        if not value:
            return {}
        on_topic = tracker.get_slot("requested_slot") == "budget" or latest.get("intent", {}).get("name") == "provide_budget"
        return {"budget": value} if on_topic else {}

    def extract_travel_start(self, dispatcher, tracker, domain):
        if tracker.get_slot("travel_start"):
            return {}
        latest = tracker.latest_message or {}
        if latest.get("intent", {}).get("name") in NON_SLOT_INTENTS:
            return {}
        text = latest.get("text") or self._entity_value(latest, "travel_start") or ""
        has_date_shape = bool(re.search(r"\d{4}-\d{2}-\d{2}", text) or resolve_relative_date(text) or "flexible" in text.lower())
        if not has_date_shape:
            return {}

        requested = tracker.get_slot("requested_slot")
        if requested == "travel_start" or tracker.get_slot("travel_end") or "flexible" in text.lower() or len(re.findall(r"\d{4}-\d{2}-\d{2}", text)) >= 2:
            return {"travel_start": text}

        if not tracker.get_slot("pending_date_phrase"):
            return {"pending_date_phrase": text}
        return {}

    def extract_travel_end(self, dispatcher, tracker, domain):
        start_value = tracker.get_slot("travel_start")
        if tracker.get_slot("travel_end") or not start_value:
            return {}
        if tracker.get_slot("requested_slot") == "travel_start":
            return {}
        latest = tracker.latest_message or {}
        if latest.get("intent", {}).get("name") in NON_SLOT_INTENTS:
            return {}
        text = latest.get("text") or ""
        relative = resolve_relative_date(text)
        if relative and relative.isoformat() == start_value:
            return {}
        iso_dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        if len(iso_dates) >= 2:
            return {}
        if len(iso_dates) == 1 and iso_dates[0] == start_value:
            return {}
        if relative or iso_dates or "flexible" in text.lower():
            return {"travel_end": text}
        return {}

    def extract_carbon_estimate_preference(self, dispatcher, tracker, domain):
        if tracker.get_slot("carbon_estimate_preference"):
            return {}
        on_topic = tracker.get_slot("requested_slot") == "carbon_estimate_preference"
        if not on_topic:
            return {}
        latest = tracker.latest_message or {}
        intent = latest.get("intent", {}).get("name")
        if intent in NON_SLOT_INTENTS:
            return {}
        if intent == "confirm_positive":
            return {"carbon_estimate_preference": "yes"}
        if intent == "confirm_negative":
            return {"carbon_estimate_preference": "no"}
        text = (latest.get("text") or "").strip().lower()
        no_phrases = ("no", "skip", "nope", "nah", "don't", "not now", "not needed")
        yes_phrases = ("yes", "show emissions", "compare emissions", "compare route emissions", "include emissions", "sure", "please", "yeah", "yep")
        if any(text == p or text.startswith(p + " ") or text.startswith(p + ",") for p in no_phrases):
            return {"carbon_estimate_preference": "no"}
        if any(text == p or text.startswith(p + " ") or text.startswith(p + ",") for p in yes_phrases):
            return {"carbon_estimate_preference": "yes"}
        return {}

    def extract_sustainability_level(self, dispatcher, tracker, domain):
        if tracker.get_slot("sustainability_level"):
            return {}
        latest = tracker.latest_message or {}
        structured = self._structured_entity_value(latest, "sustainability_level")
        if structured:
            return {"sustainability_level": structured}
        on_topic = tracker.get_slot("requested_slot") == "sustainability_level" or latest.get("intent", {}).get("name") == "provide_sustainability"
        value = self._entity_value(latest, "sustainability_level")
        if value and on_topic:
            return {"sustainability_level": value}
        if latest.get("intent", {}).get("name") in NON_SLOT_INTENTS:
            return {}
        text = (latest.get("text") or "").lower()
        keywords = ("standard", "balanced", "high", "maximum", "max", "highest", "normal", "medium")
        if not any(keyword in text for keyword in keywords):
            return {}
        if tracker.get_slot("requested_slot") == "sustainability_level":
            return {"sustainability_level": text}
        return {}

    def extract_transport_preference(self, dispatcher, tracker, domain):
        if tracker.get_slot("transport_preference"):
            return {}
        latest = tracker.latest_message or {}
        structured = self._structured_entity_value(latest, "transport_preference")
        if structured:
            return {"transport_preference": structured}
        on_topic = tracker.get_slot("requested_slot") == "transport_preference" or latest.get("intent", {}).get("name") == "provide_transport_preference"
        value = self._entity_value(latest, "transport_preference")
        if value and on_topic:
            return {"transport_preference": value}
        if latest.get("intent", {}).get("name") in NON_SLOT_INTENTS:
            return {}
        text = (latest.get("text") or "").lower()
        if not any(mode in text for mode in ("train", "flight", "bus", "car", "no preference")):
            return {}
        if tracker.get_slot("requested_slot") == "transport_preference":
            return {"transport_preference": text}
        return {}

    def extract_accommodation_preference(self, dispatcher, tracker, domain):
        if tracker.get_slot("accommodation_preference"):
            return {}
        latest = tracker.latest_message or {}
        structured = self._structured_entity_value(latest, "accommodation_preference")
        if structured:
            return {"accommodation_preference": structured}
        on_topic = tracker.get_slot("requested_slot") == "accommodation_preference" or latest.get("intent", {}).get("name") == "provide_accommodation_preference"
        value = self._entity_value(latest, "accommodation_preference")
        if value and on_topic:
            return {"accommodation_preference": value}
        if latest.get("intent", {}).get("name") in NON_SLOT_INTENTS:
            return {}
        text = (latest.get("text") or "").lower()
        keywords = ("eco", "certified", "sustainable", "budget", "cheap", "affordable", "luxury", "standard", "no preference")
        if not any(keyword in text for keyword in keywords):
            return {}
        if tracker.get_slot("requested_slot") == "accommodation_preference":
            return {"accommodation_preference": text}
        return {}

    def _geocode_and_check(self, dispatcher, value, label):
        """Shared place-name validation for origin/destination. Returns the
        geocoded place dict on success, or None (having already sent a
        rejection message) on failure."""
        if not value or len(value) > 60 or "?" in value or len(value.split()) > 6:
            dispatcher.utter_message(text=f"Please tell me a single city or place name for the {label}.")
            return None
        if not OPENCAGE_KEY:
            return {"formatted": value.title(), "short_label": value.title(), "lat": None, "lng": None}
        place = geocode(value)
        if not place or not place.get("is_place"):
            dispatcher.utter_message(text=f"I couldn't find \"{value}\" as a real place for the {label}. Please check the spelling or try a nearby larger city.")
            return None
        words = [word for word in re.findall(r"[a-zA-Z]+", value) if len(word) >= 3]
        if words:
            formatted_lower = (place.get("formatted") or "").lower()
            if not any(word.lower() in formatted_lower for word in words):
                dispatcher.utter_message(text=f"I couldn't find \"{value}\" as a real place for the {label}. Please check the spelling or try a nearby larger city.")
                return None
        return place

    def _clear_stale_transport_preference(self, tracker, distance):
        """A transport_preference can be set straight from a structured
        starter-card payload (e.g. /start_consultation{"transport_preference":
        "train"}) before the route distance is known at all - it validates
        trivially on that activation turn because feasible_transport_modes(None)
        allows every mode. Once destination/origin resolve to a real distance,
        nothing else ever re-validates an already-filled slot (the form only
        validates a slot on the turn it's newly extracted), so a since-become-
        infeasible preference would otherwise silently survive - and in
        ActionRankRecommendations, an infeasible transport_preference skips
        BOTH the flight and transit searches, leaving the user with zero
        transport options for a perfectly normal trip. Clearing it here lets
        the form re-ask (action_ask_transport_preference) with the now-known
        feasible modes."""
        current = tracker.get_slot("transport_preference")
        if not current or current == "no preference" or distance is None:
            return {}
        if current not in feasible_transport_modes(distance):
            return {"transport_preference": None}
        return {}

    def validate_destination(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"destination": None}
        place = self._geocode_and_check(dispatcher, str(slot_value).strip(), "destination")
        if not place:
            return {"destination": None}
        result = {"destination": place.get("short_label", place["formatted"])}
        origin_place = geocode(tracker.get_slot("origin")) if tracker.get_slot("origin") else None
        distance = route_distance_km(origin_place, place)
        if distance is not None:
            result["route_distance_km"] = distance
        result.update(self._clear_stale_transport_preference(tracker, distance))
        return result

    def validate_origin(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"origin": None}
        place = self._geocode_and_check(dispatcher, str(slot_value).strip(), "departure city")
        if not place:
            return {"origin": None}
        result = {"origin": place.get("short_label", place["formatted"])}
        destination_place = geocode(tracker.get_slot("destination")) if tracker.get_slot("destination") else None
        distance = route_distance_km(place, destination_place)
        if distance is not None:
            result["route_distance_km"] = distance
        result.update(self._clear_stale_transport_preference(tracker, distance))
        return result

    def validate_travel_start(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"travel_start": None}
        raw = str(slot_value).strip()
        if "flexible" in raw.lower():
            return {"travel_start": "Flexible", "travel_end": "Flexible"}
        relative = resolve_relative_date(raw)
        if relative:
            dispatcher.utter_message(text=f"Got it - departure date: {relative.isoformat()}.")
            return {"travel_start": relative.isoformat()}
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", raw)
        if len(dates) >= 2:
            try:
                start, end = date.fromisoformat(dates[0]), date.fromisoformat(dates[1])
            except ValueError:
                dispatcher.utter_message(text="Please choose valid travel dates.")
                return {"travel_start": None, "travel_end": None}
            if end <= start:
                dispatcher.utter_message(text="Your return date needs to be after your start date.")
                return {"travel_start": None, "travel_end": None}
            if start < date.today():
                dispatcher.utter_message(text="That start date has already passed. Please choose a date from today onward.")
                return {"travel_start": None, "travel_end": None}
            return {"travel_start": start.isoformat(), "travel_end": end.isoformat()}
        try:
            parsed = date.fromisoformat(raw)
        except (TypeError, ValueError):
            dispatcher.utter_message(text="Please choose a date, a phrase like \"next week\", or mark your dates as flexible.")
            return {"travel_start": None}
        if parsed < date.today():
            dispatcher.utter_message(text="That date has already passed. Please choose a date from today onward.")
            return {"travel_start": None}
        return {"travel_start": parsed.isoformat()}

    def validate_travel_end(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"travel_end": None}
        raw = str(slot_value).strip()
        if "flexible" in raw.lower():
            return {"travel_end": "Flexible"}
        relative = resolve_relative_date(raw)
        parsed = relative
        if parsed is None:
            try:
                parsed = date.fromisoformat(raw)
            except (TypeError, ValueError):
                dispatcher.utter_message(text="Please enter the return date, or a phrase like \"next month\".")
                return {"travel_end": None}
        if parsed < date.today():
            dispatcher.utter_message(text="That return date has already passed. Please choose a date from today onward.")
            return {"travel_end": None}
        start = tracker.get_slot("travel_start")
        if start and start != "Flexible":
            try:
                if parsed <= date.fromisoformat(str(start)):
                    dispatcher.utter_message(text=f"Your departure date is {start}, so the return date must be after that.")
                    return {"travel_end": None}
            except ValueError:
                pass
        if relative:
            dispatcher.utter_message(text=f"Got it - return date: {parsed.isoformat()}.")
        return {"travel_end": parsed.isoformat()}

    def validate_budget(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"budget": None}
        raw = str(slot_value).strip()
        match = re.search(r"\d[\d., ]*", raw)
        if not match:
            dispatcher.utter_message(text="Please choose or enter a numeric budget.")
            return {"budget": None}
        number = match.group().replace(" ", "")
        if "." in number and "," in number:
            decimal = "." if number.rfind(".") > number.rfind(",") else ","
            number = number.replace("." if decimal == "," else ",", "").replace(decimal, ".")
        elif "," in number:
            tail = number.rsplit(",", 1)[1]
            number = number.replace(",", "." if len(tail) in (1, 2) else "")
        elif number.count(".") > 1:
            pieces = number.split(".")
            number = "".join(pieces[:-1]) + ("." + pieces[-1] if len(pieces[-1]) in (1, 2) else pieces[-1])
        try:
            amount = float(number)
        except ValueError:
            dispatcher.utter_message(text="Please choose or enter a numeric budget.")
            return {"budget": None}
        if amount <= 0 or amount > 100_000_000:
            dispatcher.utter_message(text="Please choose an amount between 1 and 100,000,000.")
            return {"budget": None}
        distance = get_slot(tracker, "route_distance_km")
        if distance:
            minimum = round(distance * 0.05)
            if amount < minimum:
                dispatcher.utter_message(text=f"For a ~{round(distance)} km trip, {get_slot(tracker, 'currency', 'EUR')} {amount:g} is unlikely to cover real fares. Please choose at least around {minimum}.")
                return {"budget": None}
        return {"budget": f"{amount:g}"}

    def validate_carbon_estimate_preference(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"carbon_estimate_preference": None}
        value = str(slot_value).strip().lower()
        if value in {"yes", "show emissions", "compare emissions", "compare route emissions", "include emissions", "yes, compare route emissions"}:
            return {"carbon_estimate_preference": "yes"}
        if value in {"no", "skip", "skip for now", "skip carbon comparison", "no carbon breakdown"}:
            return {"carbon_estimate_preference": "no"}
        dispatcher.utter_message(text="Choose whether you'd like an emissions comparison or want to skip it for now.")
        return {"carbon_estimate_preference": None}

    def validate_sustainability_level(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"sustainability_level": None}
        value = str(slot_value).strip().lower()
        choices = {
            "maximum": ("maximum", "max", "highest"),
            "high": ("high", "very important"),
            "balanced": ("balanced", "medium"),
            "standard": ("standard", "normal"),
        }
        for choice, keywords in choices.items():
            if any(keyword in value for keyword in keywords):
                return {"sustainability_level": choice}
        dispatcher.utter_message(text="Choose standard, balanced, high, or maximum.")
        return {"sustainability_level": None}

    def validate_transport_preference(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"transport_preference": None}
        value = str(slot_value).strip().lower()
        feasible = feasible_transport_modes(get_slot(tracker, "route_distance_km"))
        if "no preference" in value or value in {"any", "doesn't matter"}:
            return {"transport_preference": "no preference"}
        for mode in ("train", "flight", "bus", "car"):
            if mode in value:
                if mode not in feasible:
                    distance = get_slot(tracker, "route_distance_km")
                    dispatcher.utter_message(text=f"Given the ~{round(distance) if distance else 'long'} km distance, {mode} isn't practical here; flight is really the only realistic option.")
                    return {"transport_preference": None}
                return {"transport_preference": mode}
        options = ", ".join(feasible)
        dispatcher.utter_message(text=f"Choose {options}, or no preference.")
        return {"transport_preference": None}

    def validate_accommodation_preference(self, slot_value, dispatcher, tracker, domain):
        if slot_value is None:
            return {"accommodation_preference": None}
        value = str(slot_value).strip().lower()
        if "no preference" in value or value in {"any", "doesn't matter"}:
            return {"accommodation_preference": "no preference"}
        choices = {
            "eco-certified": ("eco", "certified", "sustainable"),
            "budget": ("budget", "cheap", "affordable"),
            "standard": ("standard",),
            "luxury": ("luxury",),
        }
        for choice, keywords in choices.items():
            if any(keyword in value for keyword in keywords):
                return {"accommodation_preference": choice}
        dispatcher.utter_message(
            text="Choose eco-certified, budget, standard, luxury, or no preference."
        )
        return {"accommodation_preference": None}

CHANGE_INTENT_SLOTS = {
    "change_destination": ["destination", "route_distance_km"],
    "change_dates": ["travel_start", "travel_end"],
    "change_budget": ["budget"],
    "change_sustainability": ["sustainability_level"],
    "change_transport": ["transport_preference"],
    "change_accommodation": ["accommodation_preference"],
}

class ActionResetFieldAndReenterForm(Action):
    """Clears whichever field the classified change_<field> intent names,
    then re-enters consultation_form so ITS OWN already-proven extraction/
    validation logic asks for and captures the new value - replacing a
    previous design (separate action_set_<field> actions) that turned out to
    be silent no-ops: they never actually read the new answer at all, since
    the form's custom extractors only run while consultation_form is the
    active loop, and these ran with active_loop already null post-recap.
    Because every OTHER slot is still filled, the form immediately re-asks
    only this one field, then goes straight back to the recap once it's set."""

    def name(self) -> Text:
        return "action_reset_field_and_reenter_form"

    def run(self, dispatcher, tracker, domain):
        latest = tracker.latest_message or {}
        intent = latest.get("intent", {}).get("name")
        slots_to_clear = CHANGE_INTENT_SLOTS.get(intent, [])
        events = [SlotSet(slot, None) for slot in slots_to_clear]
        events.append(FollowupAction("consultation_form"))
        return events

class ActionAskDestination(Action):

    def name(self) -> Text:
        return "action_ask_destination"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(text="Where would you like to go?")
        return []

class ActionAskTravelDates(Action):

    def name(self) -> Text:
        return "action_ask_travel_start"

    def run(self, dispatcher, tracker, domain):
        pending = tracker.get_slot("pending_date_phrase")
        if pending:
            if "flexible" in pending.lower():
                dispatcher.utter_message(text=f"You mentioned \"{pending}\" earlier - I'll keep your dates flexible. Let me know if that's not right.")
                return [SlotSet("travel_start", "Flexible"), SlotSet("travel_end", "Flexible"), SlotSet("pending_date_phrase", None), FollowupAction("consultation_form")]
            relative = resolve_relative_date(pending)
            resolved = relative.isoformat() if relative else next(iter(re.findall(r"\d{4}-\d{2}-\d{2}", pending)), None)
            if resolved:
                dispatcher.utter_message(text=f"You mentioned \"{pending}\" earlier - I'll use {resolved} as your departure date. Let me know if you'd like to change it.")
                return [SlotSet("travel_start", resolved), SlotSet("pending_date_phrase", None), FollowupAction("consultation_form")]
        dispatcher.utter_message(
            text="What are your preferred dates? You can give a date, something like \"next week\", or keep them flexible."
        )
        return []

class ActionAskBudget(Action):

    def name(self) -> Text:
        return "action_ask_budget"

    def run(self, dispatcher, tracker, domain):
        currency = get_slot(tracker, "currency", "EUR")
        distance = get_slot(tracker, "route_distance_km")
        if distance:
            low, high = round(distance * 0.08), round(distance * 0.5)
            dispatcher.utter_message(text=f"Given the ~{round(distance)} km distance, a typical budget is roughly {currency} {low}-{high}. What's your budget?")
        else:
            dispatcher.utter_message(text=f"What's your comfortable travel budget in {currency}?")
        return []

class ActionAskSustainabilityPreferences(Action):

    def name(self) -> Text:
        return "action_ask_sustainability_level"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(
            text="How much would you like to prioritize sustainability? You can choose: Standard, Balanced, High, or Maximum."
        )
        return []

class ActionAskTransportationPreference(Action):

    def name(self) -> Text:
        return "action_ask_transport_preference"

    def run(self, dispatcher, tracker, domain):
        distance = get_slot(tracker, "route_distance_km")
        feasible = feasible_transport_modes(distance)
        if feasible == ["flight"]:
            dispatcher.utter_message(text=f"Given the ~{round(distance)} km distance, flying is really the only practical option, so I'll compare flights.")
            return [SlotSet("transport_preference", "flight"), FollowupAction("consultation_form")]
        options = ", ".join(mode.title() for mode in feasible)
        dispatcher.utter_message(text=f"How would you prefer to travel? Choose: {options}, or No preference.")
        return []

class ActionAskAccommodationPreference(Action):

    def name(self) -> Text:
        return "action_ask_accommodation_preference"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(
            text="What kind of stay feels right for you? Choose: Eco-certified, Budget, Standard, Luxury, or No preference."
        )
        return []
