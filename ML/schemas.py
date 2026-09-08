"""Strict backend-to-ML messages. Unknown fields and non-finite numbers fail."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class HistoryMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: ShortText


class DetectionContext(StrictModel):
    label: Literal["fire", "smoke"] = Field(alias="class")
    score: float = Field(ge=0, le=1)
    age_ms: float = Field(ge=0, le=60000)


class RobotContext(StrictModel):
    mode: Literal["manual", "auto", "unknown"] = "unknown"
    pi_connected: bool = False
    stopped: bool = True
    state_age_ms: float = Field(default=60000, ge=0, le=60000)
    control_session_id: Identifier | None = None
    operator_has_control: bool = False
    movement_executor_ready: bool = False
    speaker_available: bool = False
    latest_detection: DetectionContext | None = None


class ChatRequest(StrictModel):
    request_id: Identifier
    session_id: Identifier
    message: ShortText
    history: list[HistoryMessage] = Field(default_factory=list, max_length=12)
    context: RobotContext = Field(default_factory=RobotContext)


class SessionStart(StrictModel):
    type: Literal["session.start"]
    session_id: Identifier
    model_id: Identifier


class SessionStop(StrictModel):
    type: Literal["session.stop"]
    session_id: Identifier


class ModelSelect(StrictModel):
    type: Literal["model.select"]
    model_id: Identifier


class Heartbeat(StrictModel):
    type: Literal["heartbeat"]


class ContextUpdate(StrictModel):
    type: Literal["context.update"]
    session_id: Identifier
    context_revision: int = Field(ge=0)
    # First RGB-only adapter does not consume sensors. Explicit rejection avoids
    # accidentally suggesting that arbitrary sensor fields affect inference.


InferenceMessage = TypeAdapter(Annotated[Union[
    SessionStart, SessionStop, ModelSelect, Heartbeat, ContextUpdate
], Field(discriminator="type")])
