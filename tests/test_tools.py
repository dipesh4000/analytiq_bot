from __future__ import annotations

import pytest

from app.storage import RunLogger, SQLiteStore
from app.tools.calculator import calculate
from app.tools.toolbox import Toolbox
from app.tools.web_data import _validate_public_url


def test_calculator_supports_statistics_and_blocks_code() -> None:
    assert calculate("round(mean([10, 20, 30]) * 1.02, 2)") == 20.4
    with pytest.raises(ValueError):
        calculate("__import__('os').getcwd()")


async def test_inline_table_and_read_only_sql(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "tools.db", session_ttl_seconds=900)
    store.initialize()
    toolbox = Toolbox("unused", RunLogger(store, "b" * 32))
    loaded = await toolbox.execute(
        "load_inline_table",
        {"format": "csv", "data": "state,rate\nKerala,20\nAssam,45\n"},
    )
    dataset_id = loaded["datasets"][0]["dataset_id"]
    result = await toolbox.execute(
        "query_table",
        {
            "dataset_id": dataset_id,
            "sql": 'SELECT state, rate FROM data ORDER BY rate DESC LIMIT 1',
        },
    )
    assert result["rows"] == [{"state": "Assam", "rate": 45}]

    blocked = await toolbox.execute(
        "query_table",
        {"dataset_id": dataset_id, "sql": "DROP TABLE data"},
    )
    assert blocked["ok"] is False

    external = await toolbox.execute(
        "query_table",
        {
            "dataset_id": dataset_id,
            "sql": "SELECT * FROM read_csv_auto('https://example.com/data.csv')",
        },
    )
    assert external["ok"] is False


async def test_private_url_is_blocked() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        await _validate_public_url("http://127.0.0.1/private")
