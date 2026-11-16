"""The auto_review job must not use the pull_request_target OIDC exchange (issue #148).

anthropics/claude-code-action exchanges the workflow's OIDC token for a GitHub
App token by default. That exchange rejects `pull_request_target` runs with
"401 Unauthorized - Invalid OIDC token" (upstream anthropics/claude-code-action
issues #713 and #1886), so auto_review has to run on the job-scoped
GITHUB_TOKEN. These tests pin the pieces that make that work, and the permissions
that keep the job review-only.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "claude.yml"
ACTION = "anthropics/claude-code-action@v1"


def _workflow() -> dict:
    # BaseLoader keeps every scalar a string, so the YAML 1.1 `on:` key stays "on".
    data = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(data, dict)
    return data


def _jobs() -> dict:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _action_step(job: str) -> dict:
    steps = _jobs()[job]["steps"]
    matches = [step for step in steps if step.get("uses") == ACTION]
    assert len(matches) == 1, f"{job} should run {ACTION} exactly once"
    return matches[0]


def test_auto_review_targets_pull_request_target():
    triggers = _workflow()["on"]
    assert "pull_request_target" in triggers
    assert set(triggers["pull_request_target"]["types"]) == {
        "opened",
        "synchronize",
        "ready_for_review",
    }


def test_auto_review_uses_job_github_token_instead_of_oidc():
    step = _action_step("auto_review")
    assert step["with"]["github_token"] == "${{ secrets.GITHUB_TOKEN }}"
    # Claude's own auth is still the OAuth token; only the GitHub identity changes.
    assert step["with"]["claude_code_oauth_token"] == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
    # The OIDC exchange is what fails upstream, so the job must not request it.
    assert "id-token" not in _jobs()["auto_review"]["permissions"]


def test_auto_review_stays_review_only():
    job = _jobs()["auto_review"]
    assert job["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "actions": "read",
    }


def test_auto_review_checks_out_the_base_ref_only():
    steps = _jobs()["auto_review"]["steps"]
    checkouts = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert checkouts[0]["with"]["persist-credentials"] == "false"
    # No step may put untrusted PR head code in the workspace.
    assert "pull_request.head.sha" not in WORKFLOW.read_text(encoding="utf-8")


def test_auto_review_guard_only_accepts_grok_same_repo_prs():
    condition = _jobs()["auto_review"]["if"]
    for clause in (
        "github.event_name == 'pull_request_target'",
        "github.event.pull_request.draft == false",
        "github.event.pull_request.head.repo.full_name == github.repository",
        "github.event.pull_request.user.login == 'omarmissaoui2009-ship-it'",
        "github.actor == 'omarmissaoui2009-ship-it'",
    ):
        assert clause in condition


def test_interactive_and_tick_jobs_keep_the_app_token():
    # issue_comment and schedule events can complete the OIDC exchange, so they
    # keep posting as claude[bot] without an explicit github_token.
    for job in ("respond", "tick"):
        assert "github_token" not in _action_step(job)["with"]
        assert _jobs()[job]["permissions"]["id-token"] == "write"
