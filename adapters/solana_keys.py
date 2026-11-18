"""Pure Solana address helpers (D39, audit #271 M3). No network.

`is_on_curve` mirrors Solana's `Pubkey::is_on_curve` (ed25519 point decompression): wallets
controlled by a private key are on the curve; program-derived addresses (PDAs: pool vaults,
lockers, escrows, lending vaults, limit-order books) are off the curve and can never sign.
A token account whose *owner* is off the curve belongs to a program, so it never counts as a
holder and can never win or be paid.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _B58_INDEX:
            raise ValueError("not base58")
        n = n * 58 + _B58_INDEX[ch]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def is_on_curve(address: str) -> bool | None:
    """True for a key-pair wallet, False for a PDA, None if not a 32-byte base58 address."""
    try:
        b = b58decode(address)
    except ValueError:
        return None
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    y2 = y * y % _P
    u, v = (y2 - 1) % _P, (_D * y2 + 1) % _P
    x2 = u * pow(v, _P - 2, _P) % _P
    return x2 == 0 or pow(x2, (_P - 1) // 2, _P) == 1


def rewards_excluded(
    wallets: Iterable[str],
    *,
    configured: Iterable[str] = (),
    dev_wallets: Iterable[str] = (),
    treasury: Iterable[str] = (),
) -> dict[str, str]:
    """Address → reason, for the public excluded list. Off-curve owners, dev, treasury, list."""
    out: dict[str, str] = {}
    for w in configured:
        out[w] = "configured"
    for w in wallets:
        if is_on_curve(w) is False:
            out.setdefault(w, "program_owned_off_curve")
    for w in treasury:
        out[w] = "treasury"
    for w in dev_wallets:
        out[w] = "dev"
    return dict(sorted(out.items()))


def excluded_document(excluded: Mapping[str, str]) -> dict:
    """JSON published next to each epoch / draw so anyone can see who cannot win."""
    return {"version": 1, "count": len(excluded), "excluded": dict(sorted(excluded.items()))}
