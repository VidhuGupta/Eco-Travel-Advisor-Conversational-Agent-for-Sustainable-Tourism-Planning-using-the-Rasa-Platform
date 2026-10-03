"""Turns a completed trip brief into recommendations: transport, carbon, and activities."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Text

from rasa_sdk import Action
from rasa_sdk.events import SlotSet

from .utils import get_slot, API_HEALTH
from .geo import feasible_transport_modes
from .providers import live_flights, live_transit, live_carbon, live_activities, live_stays, nearby_sights, TRANSPORT_TO_CLIMATIQ_MODE

# Voluntary-market carbon credits are priced very differently depending on
# what they actually do: an "avoidance" credit (e.g. funding renewable
# capacity so fossil generation isn't built) is cheap per tonne; a "removal"
# credit (e.g. biochar, direct air capture) that durably pulls CO2 back out
# of the atmosphere costs far more. Bundled here as EUR-per-kg bands so the
# note can be built with a single loop rather than one line per tier.
OFFSET_PRICE_BANDS_EUR_PER_KG = {
    "credits that avoid future emissions": (0.01, 0.03),
    "credits that durably remove already-emitted CO2": (0.20, 0.50),
}

class ActionGetTransportationOptions(Action):

    def name(self) -> Text:
        return "action_get_transportation_options"

    def run(self, dispatcher, tracker, domain):
        return []

class ActionGetAccommodationOptions(Action):

    def name(self) -> Text:
        return "action_get_accommodation_options"

    def run(self, dispatcher, tracker, domain):
        return []

class ActionGetActivityOptions(Action):

    def name(self) -> Text:
        return "action_get_activity_options"

    def run(self, dispatcher, tracker, domain):
        return []

class ActionCalculateCarbonEmissions(Action):

    def name(self) -> Text:
        return "action_calculate_carbon_emissions"

    def run(self, dispatcher, tracker, domain):
        API_HEALTH["climatiq"] = None
        preference = get_slot(tracker, "carbon_estimate_preference", "yes")
        if preference == "no":
            return [SlotSet("carbon_results", None)]

        distance = get_slot(tracker, "route_distance_km")
        feasible = feasible_transport_modes(distance)
        climatiq_modes = [TRANSPORT_TO_CLIMATIQ_MODE[mode] for mode in feasible if mode in TRANSPORT_TO_CLIMATIQ_MODE]

        results = []
        if climatiq_modes:
            with ThreadPoolExecutor(max_workers=len(climatiq_modes)) as pool:
                results = [result for result in pool.map(lambda mode: live_carbon(mode, distance), climatiq_modes) if result]

        return [SlotSet("carbon_results", results)]

class ActionRankRecommendations(Action):

    def name(self) -> Text:
        return "action_rank_recommendations"

    def run(self, dispatcher, tracker, domain):

        destination = get_slot(tracker, "destination") or ""
        origin = get_slot(tracker, "origin") or ""
        budget = get_slot(tracker, "budget")
        sustainability = get_slot(tracker, "sustainability_level")
        transport_preference = get_slot(tracker, "transport_preference", "no preference")
        start, end = get_slot(tracker, "travel_start"), get_slot(tracker, "travel_end")
        currency = get_slot(tracker, "currency", "EUR")

        API_HEALTH["travelpayouts_fares"] = None
        API_HEALTH["opencage"] = None
        API_HEALTH["ticketmaster"] = None
        API_HEALTH["transitous"] = None

        distance = get_slot(tracker, "route_distance_km")
        feasible_here = feasible_transport_modes(distance)
        flight_no_search = transport_preference not in ("flight", "no preference")
        transit_no_search = transport_preference not in ("train", "bus", "no preference") or not any(mode in feasible_here for mode in ("train", "bus"))
        with ThreadPoolExecutor(max_workers=5) as pool:
            flights = pool.submit(live_flights, origin, destination, start, end, currency) if not flight_no_search else None
            transit = pool.submit(live_transit, origin, destination, start) if not transit_no_search else None
            activities = pool.submit(live_activities, destination, start, end)
            stays = pool.submit(live_stays, destination)
            sights = pool.submit(nearby_sights, destination)
            transport_options = (flights.result() if flights else []) + (transit.result() if transit else [])
            activity_options = activities.result()
            stay_options = stays.result()
            sight_options = sights.result()

        carbon_results = get_slot(tracker, "carbon_results", []) or []
        for option in transport_options:
            mode = {"flight": "air", "train": "rail", "bus": "bus", "car": "car"}.get(option.get("mode"))
            match = next((entry for entry in carbon_results if entry.get("mode") == mode), None)
            if match:
                option["emissions_kg"] = match["emissions_kg"]
                option["emissions_note"] = f"Route estimate from {match.get('source', 'Climatiq')}"

        priced_carbon = [entry for entry in carbon_results if entry.get("emissions_kg") is not None]
        if priced_carbon:
            greenest = min(priced_carbon, key=lambda entry: entry["emissions_kg"])
            greenest["recommended"] = True
            preferred_mode = {"flight": "air", "train": "rail", "bus": "bus", "car": "car"}.get(transport_preference)
            if preferred_mode:
                for entry in carbon_results:
                    if entry.get("mode") == preferred_mode:
                        entry["preferred"] = True

        target_date = None
        if start and start != "Flexible":
            try:
                target_date = date.fromisoformat(start)
            except ValueError:
                pass

        def date_distance(option):
            if not target_date or not option.get("depart_date"):
                return 999
            try:
                return abs((date.fromisoformat(option["depart_date"]) - target_date).days)
            except ValueError:
                return 999

        try:
            budget_value = float(budget) if budget else None
        except (TypeError, ValueError):
            budget_value = None
        budget_low = budget_value * 0.85 if budget_value else None
        budget_high = budget_value * 1.15 if budget_value else None

        def budget_rank(option):
            price = option.get("price")
            if price is None or budget_value is None:
                return 1
            return 0 if price <= budget_high else 2

        eco_priority = sustainability in ("high", "maximum")
        if eco_priority:
            transport_options.sort(key=lambda option: (budget_rank(option), option.get("emissions_kg") is None, option.get("emissions_kg"), date_distance(option), option.get("price") is None, option.get("price")))
        elif target_date:
            transport_options.sort(key=lambda option: (budget_rank(option), date_distance(option), option.get("price") is None, option.get("price")))
        else:
            transport_options.sort(key=lambda option: (budget_rank(option), option.get("price") is None, option.get("price")))
        transport_options[:] = transport_options[:5]
        activity_options.sort(key=lambda option: (budget_rank(option), option.get("price") is None, option.get("price")))

        if budget_value:
            for option in transport_options + activity_options:
                if option.get("price") is not None:
                    option["over_budget"] = option["price"] > budget_high
                    option["under_budget"] = option["price"] < budget_low

        priced_transport = [option for option in transport_options if option.get("price") is not None]
        if priced_transport:
            (min(priced_transport, key=lambda option: option["price"]))["badge"] = "Best price"
        carbon_ranked = [option for option in transport_options if option.get("emissions_kg") is not None]
        if len(carbon_ranked) > 1:
            min(carbon_ranked, key=lambda option: option["emissions_kg"])["badge"] = "Lowest carbon"

        if transport_options:
            transport_options[0]["recommended"] = True
        if transport_preference and transport_preference != "no preference":
            for option in transport_options:
                if option.get("mode") == transport_preference:
                    option["preferred"] = True

        recommendations = transport_options + activity_options + stay_options + sight_options
        for option in stay_options:
            option.setdefault("category", "Stay")

        total_emissions = next((option.get("emissions_kg") for option in transport_options if option.get("recommended")), None)
        if total_emissions is None and carbon_results:
            total_emissions = min((entry["emissions_kg"] for entry in carbon_results if entry.get("emissions_kg") is not None), default=None)

        price_coverage_note = "Only flights have live pricing here - train/bus show real timings but no fares, and car is carbon-only."

        offset_note = None
        if total_emissions:
            band_phrases = [
                f"{label} run roughly EUR {round(total_emissions * low, 2)} to {round(total_emissions * high, 2)}"
                for label, (low, high) in OFFSET_PRICE_BANDS_EUR_PER_KG.items()
            ]
            offset_note = (
                f"Rough offset cost for the ~{total_emissions:.0f} kg CO₂e on this trip - "
                + "; ".join(band_phrases)
                + ". These are ballpark market ranges, not a quote from any specific registry."
            )

        dispatcher.utter_message(text=f"Here's what I found for {origin} → {destination} · {currency} {budget} · Sustainability: {sustainability}")

        carbon_pref = get_slot(tracker, "carbon_estimate_preference", "yes")
        no_search_ran = flight_no_search and transit_no_search
        if not transport_options and not carbon_results:
            if carbon_pref == "no":
                note = "No live transport or carbon comparison turned up for this route/preference, and carbon comparison wasn't requested for this trip."
            else:
                note = "No live transport options or carbon data were available for this route."
        elif not transport_options:
            note = price_coverage_note if not no_search_ran else (
                f"No live search for {transport_preference} on this route (too far for train/bus, and flight wasn't wanted), "
                "but carbon is still compared across every feasible mode below."
            )
        else:
            note = price_coverage_note
        dispatcher.utter_message(json_message={
            "type": "transport", "options": transport_options, "carbon_results": carbon_results,
            "total_emissions_kg": total_emissions, "note": note, "offset_note": offset_note,
        })

        if stay_options:
            stay_note = "Real nearby places (OpenStreetMap) - no booking provider is connected, so prices/availability aren't shown."
        else:
            stay_note = "No listed places to stay turned up on OpenStreetMap for this destination."
        dispatcher.utter_message(json_message={"type": "stays", "options": stay_options, "note": stay_note})

        if activity_options:
            event_note = "Live listings from Ticketmaster."
        else:
            event_note = "No matching Ticketmaster listings for this destination and date range."
        dispatcher.utter_message(json_message={"type": "events", "options": activity_options, "note": event_note})

        if sight_options:
            sight_note = "Nearby landmarks from Wikipedia, ranked by distance."
        else:
            sight_note = "No nearby landmarks found on Wikipedia for this destination."
        dispatcher.utter_message(json_message={"type": "sights", "options": sight_options, "note": sight_note})

        dispatcher.utter_message(response="utter_offer_handover_after_results")

        return [
            SlotSet("recommendation_results", recommendations),
            SlotSet("handover_reason", "recommendations_complete"),
            SlotSet("awaiting_handover_confirm", True),
            SlotSet("awaiting_recap_confirm", False),
        ]

class ActionRecapTripDetails(Action):
    """Shows the collected trip brief and asks for button confirmation before any live search runs."""

    def name(self) -> Text:
        return "action_recap_trip_details"

    def run(self, dispatcher, tracker, domain):
        carbon_pref = "Yes" if get_slot(tracker, "carbon_estimate_preference") == "yes" else "No"
        summary = (
            "Here's the trip brief so far:\n\n"
            f"Route: {get_slot(tracker, 'origin', 'not set')} to {get_slot(tracker, 'destination', 'not set')}\n"
            f"Dates: {get_slot(tracker, 'travel_start', 'not set')} to {get_slot(tracker, 'travel_end', 'not set')}\n"
            f"Budget: {get_slot(tracker, 'currency', 'EUR')} {get_slot(tracker, 'budget', 'not set')}\n"
            f"Sustainability priority: {get_slot(tracker, 'sustainability_level', 'not set')}\n"
            f"Transport preference: {get_slot(tracker, 'transport_preference', 'not set')}\n"
            f"Accommodation preference: {get_slot(tracker, 'accommodation_preference', 'not set')}\n"
            f"Carbon comparison: {carbon_pref}\n\n"
            "Does this look right?"
        )
        dispatcher.utter_message(
            text=summary,
            buttons=[
                {"title": "Yes, find options", "payload": "/confirm_positive"},
                {"title": "I need to change something", "payload": "/confirm_negative"},
            ],
        )
        return [SlotSet("awaiting_recap_confirm", True), SlotSet("awaiting_handover_confirm", False)]

class ActionConfirmRecap(Action):
    """Chained before the live-search pipeline."""

    def name(self) -> Text:
        return "action_confirm_recap"

    def run(self, dispatcher, tracker, domain):
        return [SlotSet("confusion_count", 0)]

class ActionCompareOptions(Action):

    def name(self) -> Text:
        return "action_compare_options"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(
            text="I will compare the available options using price, estimated carbon impact and your sustainability preferences."
        )
        return []
