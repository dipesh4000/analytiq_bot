from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue, field_validator


def validate_json_value(value: Any) -> JsonValue:
    """Ensure a value can be serialized as standards-compliant JSON."""
    json.dumps(value, ensure_ascii=False, allow_nan=False)
    return value


class FinalReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: JsonValue
    log_url: HttpUrl

    @field_validator("answer")
    @classmethod
    def answer_must_be_json(cls, value: JsonValue) -> JsonValue:
        return validate_json_value(value)

    def serialize(self) -> str:
        payload = {"answer": self.answer, "log_url": str(self.log_url)}
        return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class ConversationMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LogEvent(BaseModel):
    run_id: str
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
