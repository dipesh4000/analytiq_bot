from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum


class AnalysisRoute(StrEnum):
    SMALLTALK = "smalltalk"
    DATASET = "dataset_analyst"
    SEARCH = "search_analyst"
    GENERAL = "general_analyst"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    route: AnalysisRoute
    reason: str

    @property
    def allowed_tools(self) -> frozenset[str]:
        common = {"calculate", "submit_answer"}
        if self.route == AnalysisRoute.DATASET:
            return frozenset(common | {"load_inline_table", "query_table"})
        if self.route == AnalysisRoute.SEARCH:
            return frozenset(common | {"web_search", "fetch_url", "query_table"})
        if self.route == AnalysisRoute.GENERAL:
            return frozenset(
                common
                | {"web_search", "fetch_url", "load_inline_table", "query_table"}
            )
        return frozenset()


_SMALLTALK = re.compile(
    r"^\s*(?:hi|hello|hey|hiya|thanks|thank\s+you|good\s+(?:morning|afternoon|evening))"
    r"[\s!.?]*$",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_PUBLIC_DATA_TERMS = re.compile(
    r"\b(?:mospi|data\.gov|world\s+bank|official\s+(?:data|dataset)|public\s+dataset|"
    r"census|statistical\s+abstract|latest\s+(?:data|rate|figure|statistics?))\b",
    re.IGNORECASE,
)
_FENCED_TABLE = re.compile(r"```(?:csv|tsv|json)\s*\n", re.IGNORECASE)


def route_message(text: str) -> RoutingDecision:
    """Choose one analyst without spending an LLM request."""
    if _SMALLTALK.fullmatch(text):
        return RoutingDecision(AnalysisRoute.SMALLTALK, "exact small-talk message")
    has_url = bool(_URL.search(text))
    has_inline_data = _has_inline_dataset(text)
    if has_url and has_inline_data:
        return RoutingDecision(
            AnalysisRoute.GENERAL, "mixed public source and inline data"
        )
    if has_url:
        return RoutingDecision(AnalysisRoute.SEARCH, "public URL in message")
    if has_inline_data:
        return RoutingDecision(AnalysisRoute.DATASET, "structured inline data detected")
    if _PUBLIC_DATA_TERMS.search(text):
        return RoutingDecision(AnalysisRoute.SEARCH, "public-data source or recency cue")
    return RoutingDecision(AnalysisRoute.GENERAL, "conservative full-capability fallback")


def _has_inline_dataset(text: str) -> bool:
    if _FENCED_TABLE.search(text):
        return True

    # Do not mistake the requested one-row JSON answer shape for input data.
    for match in re.finditer(r"\[[\s\S]*?\]", text):
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, list)
            and len(value) >= 2
            and all(isinstance(row, dict) for row in value)
        ):
            common_keys = set(value[0])
            if all(common_keys.intersection(row) for row in value[1:]):
                return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for delimiter in (",", "\t", "|", ";"):
        widths = [line.count(delimiter) for line in lines]
        repeated = [width for width in widths if width >= 1]
        if len(repeated) >= 3 and len(set(repeated[-3:])) == 1:
            return True
    return False
