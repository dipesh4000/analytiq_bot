from __future__ import annotations

from app.routing import AnalysisRoute, route_message


def test_exact_smalltalk_is_free_but_question_is_not() -> None:
    assert route_message("hi").route == AnalysisRoute.SMALLTALK
    assert (
        route_message("Hi, which state has the highest rate?").route
        != AnalysisRoute.SMALLTALK
    )


def test_inline_table_uses_dataset_specialist() -> None:
    question = """Which state is highest?
state,value
Assam,10
Bihar,8
Kerala,4
"""
    decision = route_message(question)
    assert decision.route == AnalysisRoute.DATASET
    assert "web_search" not in decision.allowed_tools
    assert "query_table" in decision.allowed_tools


def test_url_and_mospi_use_search_specialist() -> None:
    assert (
        route_message("Analyze https://example.org/data.csv").route
        == AnalysisRoute.SEARCH
    )
    assert (
        route_message("Which state is highest based on MOSPI data?").route
        == AnalysisRoute.SEARCH
    )


def test_requested_json_shape_is_not_mistaken_for_data() -> None:
    decision = route_message(
        'Find the value. Reply as {"answer":{"state":"<name>"},"log_url":"<url>"}'
    )
    assert decision.route == AnalysisRoute.GENERAL
