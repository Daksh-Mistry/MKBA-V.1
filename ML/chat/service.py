"""Stateless friendly chat with separately gated, deterministic gesture proposals."""

from __future__ import annotations

import json
import math
import re

from .actions import proposal, recognize
from .local_basic import reply as local_reply
from .provider import ProviderError


_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,96}", flags=re.ASCII)
_CONTEXT_KEYS = {
    "mode", "pi_connected", "stopped", "state_age_ms", "control_session_id",
    "operator_has_control", "movement_executor_ready", "latest_detection", "speaker_available",
}
_BLOCKED_TEXT = {
    "pi_disconnected": "I can't request that gesture while my Pi is disconnected.",
    "control_required": "That gesture needs the current operator's control session.",
    "executor_unavailable": "My chat movement connection isn't ready yet, so I haven't moved.",
    "manual_mode_required": "Please use manual mode before asking me for a small gesture.",
    "robot_stopped": "I'm stopped. Resume through the robot controls before asking me to move.",
    "robot_state_stale": "My robot status is too old to request movement right now.",
}


def _number(value, field: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    if not 0 <= value <= maximum or not math.isfinite(value):
        raise ValueError(f"{field} is outside its allowed range")
    return value


def validate_context(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - _CONTEXT_KEYS:
        raise ValueError("Invalid robot context fields")
    context = {
        "mode": "unknown", "pi_connected": False, "stopped": True,
        "state_age_ms": None, "control_session_id": None,
        "operator_has_control": False, "movement_executor_ready": False,
        "speaker_available": False,
        "latest_detection": None,
    }
    for field in ("pi_connected", "stopped", "operator_has_control", "movement_executor_ready", "speaker_available"):
        if field in value:
            if type(value[field]) is not bool:
                raise ValueError(f"{field} must be a boolean")
            context[field] = value[field]
    mode = value.get("mode", "unknown")
    if not isinstance(mode, str) or mode not in {"manual", "auto", "unknown"}:
        raise ValueError("Invalid robot mode")
    context["mode"] = mode
    if value.get("state_age_ms") is not None:
        context["state_age_ms"] = _number(value["state_age_ms"], "state_age_ms", 60000)
    controller = value.get("control_session_id")
    if controller is not None and (not isinstance(controller, str) or not _IDENTIFIER.fullmatch(controller)):
        raise ValueError("Invalid control session identifier")
    context["control_session_id"] = controller
    detection = value.get("latest_detection")
    if detection is not None:
        if not isinstance(detection, dict) or set(detection) != {"class", "score", "age_ms"}:
            raise ValueError("Invalid detection context")
        if not isinstance(detection["class"], str) or detection["class"] not in {"fire", "smoke"}:
            raise ValueError("Invalid detection class")
        context["latest_detection"] = {
            "class": detection["class"],
            "score": _number(detection["score"], "detection score", 1),
            "age_ms": _number(detection["age_ms"], "detection age", 60000),
        }
    return context


class ChatService:
    def __init__(self, provider=None, robot_name: str = "Robo"):
        if not isinstance(robot_name, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,40}", robot_name):
            raise ValueError("Robot name must be 1 to 40 simple characters")
        self.provider = provider
        self.robot_name = robot_name

    @property
    def mode(self) -> str:
        return "llm" if self.provider is not None and getattr(self.provider, "available", True) else "local_basic"

    async def reply(self, request: dict) -> dict:
        allowed = {"request_id", "session_id", "message", "history", "context"}
        if not isinstance(request, dict) or set(request) - allowed:
            raise ValueError("Invalid chat request fields")
        for field in ("request_id", "session_id"):
            if not isinstance(request.get(field), str) or not _IDENTIFIER.fullmatch(request[field]):
                raise ValueError(f"Invalid {field}")
        message = request.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise ValueError("message must contain 1 to 2000 characters")
        history = request.get("history", [])
        if not isinstance(history, list) or len(history) > 12:
            raise ValueError("history must contain at most 12 messages")
        clean_history = []
        for item in history:
            if not isinstance(item, dict) or set(item) != {"role", "content"}:
                raise ValueError("Invalid history message")
            if not isinstance(item["role"], str) or item["role"] not in {"user", "assistant"}:
                raise ValueError("history permits only user and assistant roles")
            if not isinstance(item["content"], str) or not item["content"].strip() or len(item["content"]) > 2000:
                raise ValueError("history content must contain 1 to 2000 characters")
            clean_history.append({"role": item["role"], "content": item["content"]})
        context = validate_context(request.get("context", {}))
        result = {
            "type": "chat.reply", "request_id": request["request_id"],
            "session_id": request["session_id"], "text": "", "action": None,
            "action_status": "none", "reason_code": None,
            "chat_mode": self.mode,
        }
        gesture = recognize(message)
        if gesture is not None:
            result["chat_mode"] = "bounded_command"
            action, reason = proposal(request, gesture, context)
            result.update(action=action, action_status="blocked" if reason else "proposed", reason_code=reason)
            if reason:
                result["text"] = _BLOCKED_TEXT[reason]
            elif gesture["kind"] == "stop":
                result["text"] = "A stop request is ready for the backend. I haven't confirmed that the robot stopped."
            else:
                d = gesture.get("direction", "center")
                cmd_type = "servo" if gesture["kind"] == "look" else "drive"
                result["text"] = f"A small gesture request is ready for the backend. I haven't moved yet. // type: '{cmd_type}' command: '{d}' //"
            return result

        if self.mode == "local_basic":
            result["text"] = local_reply(message, context, self.robot_name)
            return result

        # LLM Mode (Gemini / OpenAI compatible)
        summary = {key: context[key] for key in (
            "mode", "pi_connected", "stopped", "state_age_ms", "latest_detection", "speaker_available",
        )}
        system = (
            f"You are {self.robot_name}, a friendly and helpful Raspberry Pi robot. "
            "Speak naturally, concisely, and warmly in 1-2 sentences. "
            "You can control your camera head servos using commands to look around or express body language. "
            "If the user asks you to look, glance, turn your head, nod, or center (e.g. 'look up', 'look left', 'look right', 'center'): "
            "Append the commands at the VERY END of your response inside double slashes in this exact format: "
            "// type: 'servo' command: '<direction>' // "
            "Where <direction> can be: 'left', 'right', 'up', 'down', 'center'. "
            "For multiple movements, separate them with semicolons: "
            "// type: 'servo' command: 'up' ; type: 'servo' command: 'up' //\n"
            "If the user is having normal conversation without requesting head movement, "
            "DO NOT include any // command // block at all. "
            "Current robot status context: " + json.dumps(summary, separators=(",", ":"))
        )
        messages = [{"role": "system", "content": system}, *clean_history, {"role": "user", "content": message}]
        try:
            result["text"] = await self.provider.complete(messages)
        except ProviderError as error:
            result.update(
                text="My conversational API is unavailable, so I'm using basic local chat. "
                     + local_reply(message, context, self.robot_name),
                chat_mode="local_basic",
                reason_code=error.code,
            )
        return result

    async def close(self) -> None:
        if self.provider is not None:
            await self.provider.close()
