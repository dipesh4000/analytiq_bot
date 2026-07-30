from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from app.contracts import FinalReply


def test_final_reply_is_compact_exact_json() -> None:
    result = FinalReply(
        answer={"state": "Assam"},
        log_url="https://example.com/logs/abc.jsonl",
    ).serialize()
    assert result == (
        '{"answer":{"state":"Assam"},'
        '"log_url":"https://example.com/logs/abc.jsonl"}'
    )
    assert set(json.loads(result)) == {"answer", "log_url"}


def test_non_finite_answer_is_rejected() -> None:
    with pytest.raises((ValidationError, ValueError)):
        FinalReply(
            answer={"value": math.nan},
            log_url="https://example.com/logs/abc.jsonl",
        )
