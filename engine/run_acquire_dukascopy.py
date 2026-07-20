#!/usr/bin/env python3
"""Acquire public Dukascopy research candles; contains no trading integration."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

try:
    import pandas as pd
except ImportError:  # Keep --help/import usable enough to explain dependencies.
    pd = None  # type: ignore[assignment]
try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

BASE_URL = "https://freeserv.dukascopy.com/2.0/"
PUBLIC_PAGE = "https://www.dukascopy.com/swiss/english/marketwatch/historical/"
DEFAULT_HEADERS = {"User-Agent": "AetherForexLab-research/1.0", "Referer": PUBLIC_PAGE}
OHLC = ("open", "high", "low", "close")


class DukascopyEndpointUnavailable(RuntimeError):
    """The documented public service is not serving the requested resource."""


def require_dependencies() -> None:
    missing = [name for name, value in (("pandas", pd), ("requests", requests)) if value is None]
    if missing:
        raise RuntimeError("missing dependency: " + ", ".join(missing))


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_csv(frame: Any, path: Path) -> None:
    atomic_write(path, frame.to_csv(index=True, lineterminator="\n").encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request_json(
    session: Any,
    params: dict[str, Any],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET public JSON with bounded exponential backoff and small jitter."""
    request_params = dict(params)
    try:
        path = str(request_params.pop("path"))
    except KeyError as exc:
        raise ValueError("Dukascopy request requires a path") from exc
    url = urljoin(BASE_URL, path)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=request_params, headers=DEFAULT_HEADERS, timeout=(10, 60))
            if response.status_code in {204, 404}:
                raise DukascopyEndpointUnavailable(
                    f"Dukascopy public endpoint unavailable (HTTP {response.status_code})"
                )
            if response.status_code == 200:
                body = response.content
                if not body:
                    raise DukascopyEndpointUnavailable(
                        "Dukascopy public endpoint unavailable (HTTP 200; empty response)"
                    )
                return json.loads(body)
            if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"Dukascopy HTTP {response.status_code}")
            raise RuntimeError(f"retryable Dukascopy HTTP {response.status_code}")
        except DukascopyEndpointUnavailable:
            raise
        except (ValueError, RuntimeError, OSError) as exc:
            last = exc
            if attempt + 1 == attempts:
                break
            sleep(base_delay * (2**attempt) + random.uniform(0, base_delay / 10))
    raise RuntimeError(f"Dukascopy request failed after {attempts} attempts: {last}") from last


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "candles", "historicalPrices", "values"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("unexpected Dukascopy response schema")


def resolve_instrument_id(session: Any) -> int:
    payload = request_json(session, {"path": "api/instrumentList", "fields": "id,name"})
    for item in _records(payload):
        name = str(item.get("name", "")).replace("/", "").upper()
        if name == "EURUSD":
            return int(item["id"])
    raise ValueError("EUR/USD absent from Dukascopy public instrument list")


def normalize_candles(payload: Any, *, start: Any, end: Any, now: Any) -> Any:
    require_dependencies()
    records = _records(payload)
    aliases = {"timestamp": ("timestamp", "time", "date"), "open": ("open", "o"),
               "high": ("high", "h"), "low": ("low", "l"), "close": ("close", "c"),
               "volume": ("volume", "vol", "v")}
    rows = []
    for item in records:
        lowered = {str(k).lower(): v for k, v in item.items()}
        row = {}
        for target, names in aliases.items():
            row[target] = next((lowered[n] for n in names if n in lowered), None)
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=[*OHLC, "volume"], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    numeric_time = pd.to_numeric(frame["timestamp"], errors="coerce")
    unit = "ms" if numeric_time.dropna().abs().median() > 10_000_000_000 else "s"
    frame.index = pd.to_datetime(numeric_time, unit=unit, utc=True, errors="coerce")
    frame.index.name = "timestamp"
    frame = frame.drop(columns="timestamp")
    for column in [*OHLC, "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[~frame.index.isna()].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    start_ts, end_ts, now_ts = (pd.Timestamp(value) for value in (start, end, now))
    start_ts = start_ts.tz_localize("UTC") if start_ts.tzinfo is None else start_ts.tz_convert("UTC")
    end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
    now_ts = now_ts.tz_localize("UTC") if now_ts.tzinfo is None else now_ts.tz_convert("UTC")
    closed_end = min(end_ts, now_ts.floor("D"))
    return frame[(frame.index >= start_ts) & (frame.index < closed_end)]


def validate_integrity(frame: Any, *, end: Any, now: Any) -> dict[str, Any]:
    require_dependencies()
    values = frame[list(OHLC)].astype(float)
    finite = values.apply(lambda col: col.map(math.isfinite)).all(axis=1)
    valid = (finite & (values > 0).all(axis=1) &
             (frame.high >= frame[["open", "close"]].max(axis=1)) &
             (frame.low <= frame[["open", "close"]].min(axis=1)) & (frame.high >= frame.low))
    volume = pd.to_numeric(frame.get("volume"), errors="coerce")
    gaps = frame.index.to_series().diff()
    end_ts, now_ts = pd.Timestamp(end), pd.Timestamp(now)
    end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
    now_ts = now_ts.tz_localize("UTC") if now_ts.tzinfo is None else now_ts.tz_convert("UTC")
    cutoff = min(end_ts, now_ts.floor("D"))
    return {
        "row_count": int(len(frame)), "sorted": bool(frame.index.is_monotonic_increasing),
        "unique": bool(frame.index.is_unique), "timezone": str(frame.index.tz),
        "duplicate_bars": int(frame.index.duplicated().sum()),
        "invalid_ohlc_count": int((~valid).sum()),
        "invalid_volume_count": int((~volume.map(math.isfinite) | (volume < 0)).sum()),
        "weekend_bar_count": int((frame.index.dayofweek >= 5).sum()),
        "gaps_over_4_calendar_days": int((gaps > pd.Timedelta(days=4)).sum()),
        "incomplete_latest_candle": bool(len(frame) and frame.index.max() >= cutoff),
        "frame_fingerprint": hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest(),
    }


def acquire(start: str, end: str, output: Path, chunks: Path, *, delay: float = 0.5,
            session: Any = None, now: Any = None) -> tuple[Any, dict[str, Any]]:
    require_dependencies()
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    chunks.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    instrument_id = resolve_instrument_id(session)
    parts = []
    for year in range(start_ts.year, end_ts.year + 1):
        left, right = max(start_ts, pd.Timestamp(f"{year}-01-01", tz="UTC")), min(end_ts, pd.Timestamp(f"{year + 1}-01-01", tz="UTC"))
        if left >= right:
            continue
        chunk = chunks / f"EURUSD_1d_{year}.json"
        if chunk.exists():
            payload = json.loads(chunk.read_text())
        else:
            params = {"path": "api/historicalPrices", "instrument": instrument_id, "timeFrame": "1day",
                      "count": 5000, "start": int(left.timestamp() * 1000),
                      "end": int((right - pd.Timedelta(milliseconds=1)).timestamp() * 1000),
                      "dayStartTime": "UTC", "offerSide": "B"}
            payload = request_json(session, params)
            encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
            if len(encoded) < 3:
                raise ValueError("invalid compressed/download payload size")
            atomic_write(chunk, encoded)
            time.sleep(delay)
        parts.append(normalize_candles(payload, start=left, end=right, now=now))
    frame = pd.concat(parts).sort_index() if parts else normalize_candles([], start=start_ts, end=end_ts, now=now)
    frame = frame[~frame.index.duplicated(keep="last")]
    integrity = validate_integrity(frame, end=end_ts, now=now)
    if integrity["invalid_ohlc_count"] or not integrity["sorted"] or not integrity["unique"]:
        raise ValueError(f"Dukascopy integrity failure: {integrity}")
    atomic_csv(frame, output)
    manifest = {"source": "Dukascopy Historical Data Export / Trading Tools public service",
                "public_page": PUBLIC_PAGE, "endpoint": BASE_URL, "symbol": "EURUSD",
                "provider_instrument_id": instrument_id, "timeframe": "1day", "offer_side": "bid",
                "session_boundary": "[00:00,24:00) UTC", "requested_start": start,
                "requested_end_exclusive": end, "retrieved_at": now.isoformat(),
                "transformations": ["UTC normalization", "sort and deduplicate", "exclude incomplete candle"],
                "csv_sha256": sha256_file(output), **integrity}
    atomic_write(output.with_suffix(output.suffix + ".manifest.json"),
                 (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return frame, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire public Dukascopy EURUSD daily research candles")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default="2026-07-20", help="exclusive UTC date")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "data" / "raw_dukascopy_EURUSD_1d.csv")
    parser.add_argument("--chunks", type=Path, default=Path(__file__).parent / "data" / "dukascopy_chunks")
    args = parser.parse_args()
    acquire(args.start, args.end, args.output, args.chunks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
