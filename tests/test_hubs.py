from __future__ import annotations

from pathlib import Path

import pytest

from adapters.hubs import DEFAULT_PATH, load_hubs

REPO = Path(__file__).resolve().parent.parent


def test_default_allowlist_loads_and_has_at_least_50() -> None:
    hubs = load_hubs(DEFAULT_PATH)
    assert len(hubs) >= 50
    # Categories required by #25 are present in the committed file.
    text = DEFAULT_PATH.read_text(encoding="utf-8")
    for category in ("cex", "bridge", "relayer", "program"):
        assert f",{category}," in text


def test_load_hubs_skips_comments_and_rejects_duplicates_and_bad_keys(tmp_path: Path) -> None:
    good = "11111111111111111111111111111111"
    other = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    path = tmp_path / "hubs.csv"
    path.write_text(
        "\n".join(
            [
                "# comment header should be ignored",
                "address,label,category,source_url,accessed",
                "",
                f"{good},System Program,program,https://example.invalid/a,2026-11-14",
                f"{other},SPL Token,program,https://example.invalid/b,2026-11-14",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_hubs(path) == frozenset({good, other})

    dup = tmp_path / "dup.csv"
    dup.write_text(
        path.read_text(encoding="utf-8")
        + f"{good},again,program,https://example.invalid/c,2026-11-14\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_hubs(dup)

    bad = tmp_path / "bad.csv"
    bad.write_text(
        "address,label,category,source_url,accessed\nnot-a-key,x,cex,https://example.invalid,2026-11-14\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="base58|32 bytes"):
        load_hubs(bad)


def test_require_https_blocks_other_schemes() -> None:
    import pytest

    from adapters.hubs import require_https

    assert (
        require_https("https://api.mainnet-beta.solana.com")
        == "https://api.mainnet-beta.solana.com"
    )
    for bad in ("http://x.example", "file:///etc/passwd", "https://", "ftp://x"):
        with pytest.raises(ValueError):
            require_https(bad)
