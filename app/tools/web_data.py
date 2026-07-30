from __future__ import annotations

import asyncio
import csv
import io
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import pandas as pd
from pypdf import PdfReader

MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 12_000


async def search_web(api_key: str, query: str, max_results: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("Search query is empty")
    max_results = max(1, min(max_results, 8))
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    if "mospi" in query.lower():
        payload["include_domains"] = ["mospi.gov.in"]
    timeout = httpx.Timeout(25.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post("https://api.tavily.com/search", json=payload)
        response.raise_for_status()
        body = response.json()
    return [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("content"),
            "score": item.get("score"),
            "primary_source": _is_primary_source(item.get("url", "")),
        }
        for item in body.get("results", [])[:max_results]
    ]


async def fetch_public_url(url: str) -> tuple[bytes, str, str]:
    """Fetch a URL while blocking private-network and metadata destinations."""
    current = url.strip()
    timeout = httpx.Timeout(35.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(5):
            await _validate_public_url(current)
            async with client.stream(
                "GET",
                current,
                headers={"User-Agent": "AnalytiqBot/1.0 (+public data analysis)"},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect has no location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise ValueError("Download exceeds 15 MB limit")
                    chunks.append(chunk)
                content_type = response.headers.get("content-type", "").split(";")[0].lower()
                return b"".join(chunks), content_type, str(response.url)
    raise ValueError("Too many redirects")


async def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP(S) URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not supported")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, port, type=socket.SOCK_STREAM
    )
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("Private or unsafe network destination blocked")


def extract_content(
    content: bytes, content_type: str, source_url: str, *, focus: str = ""
) -> tuple[str, list[pd.DataFrame]]:
    """Extract compact text and tables from common public-data formats."""
    lower_url = source_url.lower().split("?", 1)[0]
    tables: list[pd.DataFrame] = []
    text = ""

    if "spreadsheet" in content_type or lower_url.endswith((".xlsx", ".xls")):
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
        tables = [frame for frame in list(sheets.values())[:8] if not frame.empty]
        text = f"Excel workbook with sheets: {list(sheets)[:8]}"
    elif content_type == "application/pdf" or lower_url.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:80])
    elif "json" in content_type or lower_url.endswith((".json", ".jsonl")):
        decoded = content.decode("utf-8-sig", errors="replace")
        payload = json.loads(decoded)
        if isinstance(payload, list):
            tables = [pd.json_normalize(payload)]
        elif isinstance(payload, dict):
            list_values = [value for value in payload.values() if isinstance(value, list)]
            tables = [pd.json_normalize(value) for value in list_values[:8] if value]
            if not tables:
                tables = [pd.json_normalize(payload)]
        text = decoded
    elif "html" in content_type or lower_url.endswith((".html", ".htm")):
        decoded = content.decode("utf-8", errors="replace")
        try:
            tables = [frame for frame in pd.read_html(io.StringIO(decoded))[:8] if not frame.empty]
        except ValueError:
            tables = []
        text = _html_to_text(decoded)
    else:
        decoded = content.decode("utf-8-sig", errors="replace")
        delimiter = "\t" if lower_url.endswith(".tsv") else _detect_delimiter(decoded)
        try:
            frame = pd.read_csv(io.StringIO(decoded), sep=delimiter)
            if frame.shape[1] > 1 or lower_url.endswith((".csv", ".tsv")):
                tables = [frame]
        except Exception:
            tables = []
        text = decoded

    return _compact_text(text, focus), [
        _clean_frame(frame) for frame in tables if not frame.empty
    ]


def parse_inline_table(data: str, data_format: str) -> list[pd.DataFrame]:
    kind = data_format.lower()
    if kind == "json":
        payload = json.loads(data)
        return [_clean_frame(pd.json_normalize(payload))]
    if kind in {"csv", "tsv"}:
        separator = "\t" if kind == "tsv" else ","
        return [_clean_frame(pd.read_csv(io.StringIO(data), sep=separator))]
    raise ValueError("format must be csv, tsv, or json")


def _detect_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:8_000], delimiters=",\t;|").delimiter
    except csv.Error:
        return ","


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    cleaned.columns = [
        " | ".join(str(part) for part in column if str(part) != "nan")
        if isinstance(column, tuple)
        else str(column)
        for column in cleaned.columns
    ]
    return cleaned


def _html_to_text(html: str) -> str:
    try:
        from lxml import html as lxml_html

        root = lxml_html.fromstring(html)
        for bad in root.xpath("//script|//style|//noscript"):
            bad.drop_tree()
        return "\n".join(part.strip() for part in root.text_content().splitlines() if part.strip())
    except Exception:
        return html


def _compact_text(text: str, focus: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    terms = [
        phrase.strip().lower()
        for phrase in (
            [focus]
            + focus.replace("/", " ").replace("-", " ").split()
            + [
                "maternal mortality ratio",
                "maternal mortality",
                "state/union territory",
                "state",
                "table",
            ]
        )
        if len(phrase.strip()) >= 4
    ]
    lowered = text.lower()
    windows: list[tuple[int, int]] = [(0, 5_000)]
    for term in dict.fromkeys(terms):
        start = 0
        matches: list[int] = []
        while len(matches) < 30:
            index = lowered.find(term, start)
            if index < 0:
                break
            matches.append(index)
            start = index + len(term)
        for index in matches:
            windows.append((max(0, index - 1_800), min(len(text), index + 4_200)))

    parts: list[str] = []
    used: list[tuple[int, int]] = []
    total = 0
    for start, end in windows:
        if any(start >= old_start and end <= old_end for old_start, old_end in used):
            continue
        piece = text[start:end]
        remaining = MAX_TEXT_CHARS - total
        if remaining <= 0:
            break
        parts.append(piece[:remaining])
        total += min(len(piece), remaining)
        used.append((start, end))
    return "\n\n--- focused excerpt ---\n\n".join(parts)


def _is_primary_source(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname.endswith((".gov.in", ".nic.in")) or hostname == "mospi.gov.in"
