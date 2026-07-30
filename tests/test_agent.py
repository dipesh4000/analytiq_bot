from __future__ import annotations

from app.agent import (
    _compact_history,
    _explicitly_requests_null,
    _parse_content_candidate,
    _parse_submitted_answer,
)
from app.contracts import ConversationMessage


def test_model_outer_wrapper_is_reduced_to_answer_value() -> None:
    submitted = _parse_submitted_answer(
        '{"answer":{"state":"Assam"},"log_url":"https://made-up.example/run.jsonl"}'
    )
    assert submitted == {"state": "Assam"}

    recovered = _parse_content_candidate(
        '{"answer":{"state":"Assam"},"log_url":"https://made-up.example/run.jsonl"}'
    )
    assert recovered == {"state": "Assam"}


def test_null_requires_explicit_request() -> None:
    assert not _explicitly_requests_null("Which state is highest?")
    assert _explicitly_requests_null("Return JSON null when no row matches.")


def test_history_compaction_keeps_latest_message() -> None:
    history = [
        ConversationMessage(role="user", content=f"{index}:" + ("x" * 3_000))
        for index in range(10)
    ]
    compact = _compact_history(history)
    assert compact[-1].content.startswith("9:")
    assert len(compact) <= 8
