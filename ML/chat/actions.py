"""Recognize one explicit gesture and propose it; never emit Pi wire commands."""

from __future__ import annotations

import re
from uuid import uuid4


_COMMAND = re.compile(
    r"(?:please )?(?:can you |could you )?(?:please )?"
    r"(?P<command>stop|look (?:left|right|up|down)|"
    r"move (?:(?:a little(?: bit)?|a bit) )?(?:forward|backward|backwards)|"
    r"turn (?:left|right))"
    r"(?: please)?[.!?]?",
    flags=re.ASCII,
)


def recognize(message: str) -> dict | None:
    """Full-match only: quoted, negated, multi-step or embedded commands fail."""
    normalized = " ".join(message.lower().split())
    match = _COMMAND.fullmatch(normalized)
    if match is None:
        return None
    command = match.group("command")
    if command == "stop":
        return {"kind": "stop"}
    direction = command.split()[-1]
    if command.startswith("look "):
        return {"kind": "look", "direction": direction, "degrees": 5}
    if command.startswith("turn "):
        direction = "turn_" + direction
    elif direction == "backwards":
        direction = "backward"
    return {"kind": "move", "direction": direction, "duration_ms": 300, "speed": 0.2}


def proposal(request: dict, gesture: dict, context: dict) -> tuple[dict | None, str | None]:
    """These gates are advisory; the backend MUST recheck before execution."""
    if not context["pi_connected"]:
        return None, "pi_disconnected"
    if not context["operator_has_control"] or context["control_session_id"] != request["session_id"]:
        return None, "control_required"
    if not context["movement_executor_ready"]:
        return None, "executor_unavailable"
    # Stop is allowed in auto, during stale telemetry, and when already stopped.
    if gesture["kind"] != "stop":
        if context["mode"] != "manual":
            return None, "manual_mode_required"
        if context["stopped"]:
            return None, "robot_stopped"
        if context["state_age_ms"] is None or context["state_age_ms"] > 1000:
            return None, "robot_state_stale"
    return {
        "action_id": str(uuid4()), "request_id": request["request_id"],
        "session_id": request["session_id"], "status": "proposed",
        "valid_for_ms": 1000, **gesture,
    }, None
