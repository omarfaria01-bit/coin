"""Load the public hubs allowlist used by the sybil modules (fee payer / first funder)."""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

import base58

REQUIRED_COLUMNS = ("address", "label", "category", "source_url", "accessed")
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "hubs" / "solana_hubs.csv"


def _require_pubkey(address: str, line: int) -> str:
    try:
        raw = base58.b58decode(address)
    except ValueError as exc:
        raise ValueError(f"line {line}: address is not valid base58: {address}") from exc
    if len(raw) != 32:
        raise ValueError(f"line {line}: address must decode to 32 bytes, got {len(raw)}: {address}")
    return address


def load_hubs(path: Path | str = DEFAULT_PATH) -> frozenset[str]:
    """Return unique hub addresses from a CSV. Comment lines (#) and blanks are ignored."""
    path = Path(path)
    seen: dict[str, int] = {}
    out: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        logical = 0
        header: list[str] | None = None
        for raw in fh:
            logical += 1
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if header is None:
                header = next(csv.reader([line]))
                missing = [c for c in REQUIRED_COLUMNS if c not in header]
                if missing:
                    raise ValueError(f"missing columns: {missing}")
                continue
            row = next(csv.reader([line]))
            if len(row) != len(header):
                raise ValueError(f"line {logical}: expected {len(header)} columns, got {len(row)}")
            rec = dict(zip(header, row, strict=True))
            address = rec["address"].strip()
            if not address:
                raise ValueError(f"line {logical}: empty address")
            if not rec["source_url"].strip():
                raise ValueError(f"line {logical}: every hub must have a source_url")
            if address in seen:
                raise ValueError(
                    f"line {logical}: duplicate address (first seen on line {seen[address]})"
                )
            seen[address] = logical
            out.add(_require_pubkey(address, logical))
    return frozenset(out)


def require_https(url: str) -> str:
    """Return url if it is an https URL with a host; else ValueError (blocks file:, http:, ...)."""
    parsed = urlparse(url) if isinstance(url, str) else None
    if parsed is None or parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"only https URLs are allowed, got {url!r}")
    return url
