"""Small offline replies based only on validated backend context.

This is ordinary code, not a language model. It never returns actions and does
not treat previous conversation as evidence about the robot's current state.
"""
from __future__ import annotations

import re


STATE_MAX_AGE_MS = 1000
DETECTION_MAX_AGE_MS = 750


def _fresh(context: dict) -> bool:
    return (context["pi_connected"] and context["state_age_ms"] is not None
            and context["state_age_ms"] <= STATE_MAX_AGE_MS)


def _status(context: dict) -> str:
    if not context["pi_connected"]:
        return "My Pi is disconnected. I don't have a current hardware status."
    if not _fresh(context):
        return "My Pi connection is present, but my hardware status is missing or stale. I can't confirm my current state."
    mode = context["mode"]
    mode_text = f"{mode} mode" if mode != "unknown" else "an unknown mode"
    state = "stopped" if context["stopped"] else "resumed"
    return (f"The backend reports that my Pi is connected, in {mode_text}, and {state}. "
            "Resumed permits new requests; the backend still checks each action. "
            "A connection doesn't confirm every actuator is available or that my wheels are moving.")


def _detection(context: dict) -> str:
    if not _fresh(context):
        return "I don't have fresh connected robot status, so I can't give a current detection report."
    detection = context["latest_detection"]
    if detection is None:
        return "The backend hasn't supplied a recent fire or smoke detection. That doesn't prove the scene is safe, or that vision is running."
    if detection["age_ms"] > DETECTION_MAX_AGE_MS:
        return "The last detection is stale, so I can't describe it as a current observation."
    score = round(detection["score"] * 100)
    return (f"The detector reported possible {detection['class']} with a model score of {score}%. "
            "That's a model estimate, not confirmed fire. I receive detection summaries, not camera images.")


def reply(message: str, context: dict, robot_name: str) -> str:
    """Choose a friendly reply without network access or command interpretation."""
    normalized = " ".join(message.casefold().split())
    words = set(re.findall(r"[a-z]+", normalized, flags=re.ASCII))
    if (words & {"fire", "smoke", "detection", "detections", "camera", "see", "seeing"}
            and not words & {"move", "turn", "pump", "spray", "shutdown"}):
        return _detection(context)
    if words & {"status", "connected", "connection", "stopped", "mode"} or normalized.rstrip("?.!") in {
        "how are you", "how are you doing", "are you okay", "are you ok", "what are you doing",
    }:
        return _status(context)
    if words & {"speaker", "speak", "speech", "voice", "talk", "audio"}:
        if context["speaker_available"] and _fresh(context):
            return ("The backend reports that speaker output is available. With Speak replies enabled, "
                    "it can send my reply to the Pi. I can't confirm audio playback from here.")
        return "Speaker output isn't confirmed available in my current status. I can still reply here in text."
    if words & {"help", "capabilities", "commands"} or normalized.rstrip("?.!") in {
        "what can you do", "what do you do", "what can i ask", "what can i ask you",
    }:
        return ("I can share robot status and detector summaries, and handle simple requests without an API key. "
                "Try 'status', 'what do you see?', 'look right', 'move forward', or 'stop'. "
                "One exact gesture at a time goes through backend control checks. "
                "Use the UI for pump, auto mode, and shutdown. My basic local chat is not an LLM.")
    if re.fullmatch(r"(?:hi|hello|hey|good morning|good afternoon|good evening)(?: robo)?[.!?]*", normalized):
        return (f"Hi! I'm {robot_name}, your robot. My basic local chat works without an API key. "
                "Ask for my status, what the detector sees, or help with a small gesture.")
    if re.fullmatch(r"(?:thanks|thank you|thank you robo|thanks robo)[.!?]*", normalized):
        return "You're welcome! I'm here when you want a status update or a small gesture."
    if words & {"name", "human", "alive", "feel", "feelings"} or normalized.rstrip("?.!") in {
        "who are you", "what are you",
    }:
        return (f"I'm {robot_name}, a Raspberry Pi robot. This is my basic local chat, written in ordinary code. "
                "I don't have human feelings. An optional LLM API key enables more flexible conversation.")
    if words & {"joke", "jokes"}:
        return "My idea of a workout is running a loop. That's a robot joke, not a movement request!"
    return ("I'm using basic local chat, so I can help with robot status, detection summaries and simple gestures. "
            "Try 'help' or ask one exact request such as 'look right'. "
            "I haven't requested any robot action. An optional LLM API key enables broader conversation.")
