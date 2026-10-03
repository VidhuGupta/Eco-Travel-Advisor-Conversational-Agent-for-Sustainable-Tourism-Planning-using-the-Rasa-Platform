"""Modify-trip, human handover, and the confusion-escalation mechanism:
repeated unclear/off-topic turns lead to a real yes/no human-handover offer
rather than either silently looping or handing over without asking."""
from typing import Text

from rasa_sdk import Action
from rasa_sdk.events import FollowupAction, SlotSet, UserUtteranceReverted

from .utils import get_slot

CONFUSION_HANDOVER_THRESHOLD = 2

class ActionModifyTrip(Action):

    def name(self) -> Text:
        return "action_modify_trip"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(text="Sure. Which part of the trip would you like to change?")
        return []

class ActionOfferHumanHandover(Action):

    def name(self) -> Text:
        return "action_offer_human_handover"

    def run(self, dispatcher, tracker, domain):

        dispatcher.utter_message(response="utter_confirm_human_handover")
        return [
            SlotSet("handover_reason", "requested"),
            SlotSet("awaiting_handover_confirm", True),
            SlotSet("awaiting_recap_confirm", False),
        ]

class ActionHumanHandover(Action):

    def name(self) -> Text:
        return "action_human_handover"

    def run(self, dispatcher, tracker, domain):

        reason = get_slot(tracker, "handover_reason", "requested")
        context = {
            "destination": get_slot(tracker, "destination"),
            "origin": get_slot(tracker, "origin"),
            "travel_start": get_slot(tracker, "travel_start"),
            "travel_end": get_slot(tracker, "travel_end"),
            "budget": get_slot(tracker, "budget"),
            "sustainability": get_slot(tracker, "sustainability_level"),
            "transport": get_slot(tracker, "transport_preference"),
            "accommodation": get_slot(tracker, "accommodation_preference"),
            "reason": reason,
        }

        dispatcher.utter_message(
            text="You're connected. I've shared your full trip context with a human advisor, "
                 "and they'll pick up this conversation from here."
        )
        dispatcher.utter_message(json_message={"handover": True, "handover_context": context})

        return [
            SlotSet("handover_context", context),
            SlotSet("confusion_count", 0),
            SlotSet("awaiting_handover_confirm", False),
            SlotSet("handover_reason", None),
        ]

class ActionUnsupportedTopic(Action):

    def name(self) -> Text:
        return "action_unsupported_topic"

    def run(self, dispatcher, tracker, domain):

        count = int(get_slot(tracker, "confusion_count", 0) or 0) + 1

        if count >= CONFUSION_HANDOVER_THRESHOLD:
            dispatcher.utter_message(response="utter_offer_handover")
            return [
                SlotSet("confusion_count", 0),
                SlotSet("handover_reason", "confusion"),
                SlotSet("awaiting_handover_confirm", True),
                SlotSet("awaiting_recap_confirm", False),
            ]

        dispatcher.utter_message(response="utter_unsupported_topic")
        return [SlotSet("confusion_count", count)]

class ActionContinueAfterHandoverOffer(Action):

    def name(self) -> Text:
        return "action_continue_after_handover_offer"

    def run(self, dispatcher, tracker, domain):

        dispatcher.utter_message(response="utter_continue_with_bot")
        return [SlotSet("awaiting_handover_confirm", False), SlotSet("handover_reason", None)]

class ActionDefaultFallback(Action):

    def name(self) -> Text:
        return "action_default_fallback"

    def run(self, dispatcher, tracker, domain):

        if tracker.active_loop and tracker.active_loop.get("name"):
            return [FollowupAction(tracker.active_loop["name"])]

        count = int(get_slot(tracker, "confusion_count", 0) or 0) + 1

        if count >= CONFUSION_HANDOVER_THRESHOLD:
            dispatcher.utter_message(response="utter_offer_handover")
            return [
                UserUtteranceReverted(),
                SlotSet("confusion_count", 0),
                SlotSet("handover_reason", "confusion"),
                SlotSet("awaiting_handover_confirm", True),
                SlotSet("awaiting_recap_confirm", False),
            ]

        dispatcher.utter_message(response="utter_fallback")
        return [UserUtteranceReverted(), SlotSet("confusion_count", count)]
