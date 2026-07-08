"""Redacting logger — secrets are never written to stdout/logs/UI."""
from __future__ import annotations
import re

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|bk|sk|ak)[=:\s\"']+([\w\-]{8,})"
)


def redact(text: str) -> str:
    """Replace any secret-looking assignment value with [REDACTED]."""
    if not isinstance(text, str):
        text = str(text)
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)


def log(msg: str) -> None:
    print(redact(msg))
