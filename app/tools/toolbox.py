from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from typing import Any

import duckdb
import pandas as pd

from app.storage import RunLogger
from app.tools.calculator import calculate
from app.tools.web_data import (
    extract_content,
    fetch_public_url,
    parse_inline_table,
    search_web,
)

_BLOCKED_SQL = re.compile(
    r"\b(attach|copy|create|delete|drop|export|import|insert|install|load|pragma|"
    r"replace|set|update|vacuum|call)\b",
    re.IGNORECASE,
)


class Toolbox:
    def __init__(
        self,
        tavily_api_key: str,
        logger: RunLogger,
        *,
        allowed_tools: frozenset[str] | None = None,
    ) -> None:
        self.tavily_api_key = tavily_api_key
        self.logger = logger
        self.tables: dict[str, pd.DataFrame] = {}
        self.sources: list[str] = []
        self.allowed_tools = allowed_tools
        self._cache: dict[str, dict[str, Any]] = {}
        self._calls: Counter[str] = Counter()

    @staticmethod
    def schemas(allowed_tools: frozenset[str] | None = None) -> list[dict[str, Any]]:
        schemas = [
            _tool(
                "web_search",
                "Search the public web for authoritative datasets or supporting sources.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                ["query"],
            ),
            _tool(
                "fetch_url",
                "Fetch a public URL and extract focused text plus registered data tables.",
                {
                    "url": {"type": "string"},
                    "focus": {
                        "type": "string",
                        "description": "Metric or phrase to prioritize in a long document.",
                    },
                },
                ["url"],
            ),
            _tool(
                "load_inline_table",
                "Load CSV, TSV, or JSON copied from the user's message into a queryable table.",
                {
                    "data": {"type": "string"},
                    "format": {"type": "string", "enum": ["csv", "tsv", "json"]},
                },
                ["data", "format"],
            ),
            _tool(
                "query_table",
                "Run read-only DuckDB SQL against one registered table. Refer to it as data.",
                {
                    "dataset_id": {"type": "string"},
                    "sql": {"type": "string"},
                },
                ["dataset_id", "sql"],
            ),
            _tool(
                "calculate",
                "Evaluate arithmetic or basic statistics such as mean([1,2,3]).",
                {"expression": {"type": "string"}},
                ["expression"],
            ),
            _tool(
                "submit_answer",
                "Finish. answer_json must be only the requested JSON value for answer.",
                {
                    "answer_json": {"type": "string"},
                    "evidence_sources": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                ["answer_json"],
            ),
        ]
        if allowed_tools is None:
            return schemas
        return [
            schema
            for schema in schemas
            if schema["function"]["name"] in allowed_tools
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.allowed_tools is not None and name not in self.allowed_tools:
            result = {"ok": False, "error": f"Tool {name} is not allowed for this route"}
            await self.logger.log("tool_blocked", tool=name, error=result["error"])
            return result

        cache_key = json.dumps(
            [name, arguments], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if cache_key in self._cache:
            await self.logger.log("tool_cache_hit", tool=name)
            return self._cache[cache_key]

        budgets = {
            "web_search": 2,
            "fetch_url": 4,
            "load_inline_table": 2,
            "query_table": 6,
            "calculate": 4,
        }
        self._calls[name] += 1
        if self._calls[name] > budgets.get(name, 1):
            result = {"ok": False, "error": f"Tool call budget exceeded for {name}"}
            await self.logger.log("tool_budget_exceeded", tool=name)
            return result

        await self.logger.log("tool_started", tool=name, arguments=arguments)
        try:
            if name == "web_search":
                result = {
                    "results": await search_web(
                        self.tavily_api_key,
                        str(arguments["query"]),
                        int(arguments.get("max_results", 5)),
                    )
                }
            elif name == "fetch_url":
                result = await self._fetch(
                    str(arguments["url"]), str(arguments.get("focus", ""))
                )
            elif name == "load_inline_table":
                frames = parse_inline_table(
                    str(arguments["data"]), str(arguments["format"])
                )
                result = {"datasets": self._register_tables(frames, source="inline")}
            elif name == "query_table":
                result = self._query(
                    str(arguments["dataset_id"]), str(arguments["sql"])
                )
            elif name == "calculate":
                result = {"value": calculate(str(arguments["expression"]))}
            else:
                raise ValueError(f"Unknown tool: {name}")
            await self.logger.log("tool_completed", tool=name, result=result)
            response = {"ok": True, **result}
            self._cache[cache_key] = response
            return response
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            await self.logger.log("tool_failed", tool=name, error=error)
            return {"ok": False, "error": error}

    async def _fetch(self, url: str, focus: str = "") -> dict[str, Any]:
        content, content_type, final_url = await fetch_public_url(url)
        text, frames = extract_content(content, content_type, final_url, focus=focus)
        if final_url not in self.sources:
            self.sources.append(final_url)
        return {
            "final_url": final_url,
            "content_type": content_type,
            "text": text,
            "datasets": self._register_tables(frames, source=final_url),
        }

    def _register_tables(
        self, frames: list[pd.DataFrame], *, source: str
    ) -> list[dict[str, Any]]:
        registered = []
        for frame in frames[:6]:
            dataset_id = f"ds_{uuid.uuid4().hex[:10]}"
            self.tables[dataset_id] = frame
            sample = frame.head(3).where(pd.notna(frame.head(3)), None)
            registered.append(
                {
                    "dataset_id": dataset_id,
                    "source": source,
                    "rows": int(len(frame)),
                    "columns": [str(column) for column in frame.columns],
                    "sample": json.loads(sample.to_json(orient="records", date_format="iso")),
                }
            )
        return registered

    def _query(self, dataset_id: str, sql: str) -> dict[str, Any]:
        if dataset_id not in self.tables:
            raise ValueError("Unknown dataset_id")
        statement = sql.strip().rstrip(";").strip()
        if ";" in statement or not re.match(r"^(select|with)\b", statement, re.IGNORECASE):
            raise ValueError("Only one SELECT query is allowed")
        if _BLOCKED_SQL.search(statement):
            raise ValueError("Unsafe SQL keyword blocked")
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute("SET enable_external_access = false")
            connection.register("data", self.tables[dataset_id])
            result = connection.execute(
                f"SELECT * FROM ({statement}) AS analytiq_result LIMIT 50"
            ).fetchdf()
        finally:
            connection.close()
        records = json.loads(
            result.where(pd.notna(result), None).to_json(orient="records", date_format="iso")
        )
        return {
            "columns": [str(column) for column in result.columns],
            "row_count": len(records),
            "rows": records,
        }


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }
