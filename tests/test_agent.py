from __future__ import annotations

from app.agent import _parse_content_candidate, _parse_submitted_answer


def test_model_outer_wrapper_is_reduced_to_answer_value() -> None:
    submitted = _parse_submitted_answer(
        '{"answer":{"state":"Assam"},"log_url":"https://made-up.example/run.jsonl"}'
    )
    assert submitted == {"state": "Assam"}

    recovered = _parse_content_candidate(
        '{"answer":{"state":"Assam"},"log_url":"https://made-up.example/run.jsonl"}'
    )
    assert recovered == {"state": "Assam"}
