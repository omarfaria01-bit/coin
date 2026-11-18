"""#326 (kiwi 18 Nov 20:20): Founder coin (8HXsCM...4upump) in the vocabulary and the seed.

"Founder" is an everyday English word, so it sits in the narrowest tier, `needs_context`: it makes
a coin a candidate only next to a strong GTA word or a second ambiguous word, never alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from index.filters import gta_match
from index.params import IndexParams

ROOT = Path(__file__).resolve().parents[1]
FOUNDER = "8HXsCMy8ma8QP2yVZXG5SZYyaTZw5AUrUDha1G4upump"
P = IndexParams.model_validate(json.loads((ROOT / "index/params.json").read_text()))


def test_founder_is_a_context_word_only() -> None:
    assert "Founder" in P.keywords.needs_context
    assert "Founder" not in P.keywords.strong
    assert "Founder" not in P.discovery.search_terms  # the seed is enough (#326 step 3)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Founder FOUNDER", False),  # alone: unrelated "Founder" coins stay out
        ("Founder FOUNDER Founder of a startup", False),
        ("Founder FOUNDER the Dacity founder", True),  # strong word = GTA context
        ("Founder FOUNDER Vice City", True),
        ("Founder FOUNDER Vice", True),  # second ambiguous word
        # D41: a generic word (Meme, Core, ...) next to an ambiguous word is enough context.
        # So "Founder meme coin" IS a candidate; recorded in the PR for the manager.
        ("Founder FOUNDER the first meme", True),
        ("Cofounder COFOUNDER", False),  # word boundaries
    ],
)
def test_founder_needs_gta_context(text: str, ok: bool) -> None:
    assert gta_match(text, P) is ok


def test_founder_is_seeded() -> None:
    seeds = (ROOT / "index/seed_mints.txt").read_text()
    assert any(line.split()[0] == FOUNDER for line in seeds.splitlines() if line and line[0] != "#")
