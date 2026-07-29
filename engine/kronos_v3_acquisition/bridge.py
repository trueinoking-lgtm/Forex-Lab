"""Metadata-only HTTP client for the read-only Windows MT5 bridge."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .collector import AcquisitionError, D1Bar, SourceIdentity


class BridgeRequestError(AcquisitionError):
    def __init__(self, category: str, stage: str, http_status: int | None = None):
        super().__init__(f"{category} at {stage}")
        self.category = category
        self.stage = stage
        self.http_status = http_status


@dataclass
class MetadataBridgeClient:
    base_url: str
    token: str
    timeout: float = 8.0
    last_http_status: int | None = None

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        suffix = "?" + urllib.parse.urlencode(params) if params else ""
        request = urllib.request.Request(
            self.base_url.rstrip("/") + path + suffix,
            headers={"Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.last_http_status = int(response.status)
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            category = (
                "BRIDGE_AUTHENTICATION_FAILED"
                if exc.code in (401, 403)
                else "BRIDGE_CONNECTIVITY_FAILED"
            )
            raise BridgeRequestError(category, path, exc.code) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise BridgeRequestError("BRIDGE_CONNECTIVITY_FAILED", path) from exc

    def health(self) -> dict:
        return self._get("/health")

    def account(self) -> dict:
        body = self._get("/account")
        body.pop("login", None)
        body.pop("balance", None)
        body.pop("equity", None)
        return body

    def symbols(self) -> dict[str, str]:
        body = self._get("/symbols")
        return {str(key): str(value) for key, value in body["symbol_map"].items()}

    def d1_metadata(self, symbol: str, count: int = 32) -> tuple[SourceIdentity, list[D1Bar]]:
        body = self._get(
            "/d1-metadata", {"symbol": symbol, "count": str(count)}
        )
        source = SourceIdentity(
            broker_company=str(body["company"]),
            broker_server=str(body["server"]),
            symbol=symbol,
            provider_symbol=str(body["provider_symbol"]),
            timeframe=str(body["timeframe"]),
            broker_mode=str(body["broker_mode"]),
        )
        bars = [D1Bar.metadata(value) for value in body["bar_open_timestamps"]]
        return source, bars
