"""Scenario registry for `sim.run --scenario` (red-team exploit repros go here, PROMPT_GROK).

The v0.2 sniper/flipper scenarios scored with the deleted float engine; their v0.3.3 checks
are the sniper and scalper rows in `sim.acceptance_v033` and `sim.epoch_runner` (#84).
A scenario returns a dict with "pass": True, False or "skipped".
"""

from __future__ import annotations

from collections.abc import Callable

REGISTRY: dict[str, Callable[[int], dict]] = {}
