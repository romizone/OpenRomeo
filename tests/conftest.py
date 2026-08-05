"""Shared pytest fixtures.

`fake_slack` boots the in-process FakeSlack harness on an ephemeral port and points the Slack
adapter at it via `SLACK_API_URL`, so the real `SlackAdapter` / `slack_bolt` stack runs
end-to-end with no network, tokens, or the Slack app console. See
`coworker.testing.fake_slack` and `platform/docs/FAKE-SLACK-SPEC.md`.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from coworker.testing.fake_slack import FakeSlack


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    """EVERY test gets an isolated SecretStore/state dir. Without this, any test that builds
    a SessionManager reads the developer's real machine-global state — including their cloud
    sign-in, which made test session creation emit REAL telemetry to prod (found 2026-07-03
    as burst noise in the ocw-connect-telemetry-events table)."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "coworker-state"))


@pytest.fixture(autouse=True)
def _isolated_scratch_base(tmp_path, monkeypatch):
    """…and an isolated scratch base. Orphan knowledge sessions auto-provision a scratch dir
    from this, so without the override every such test littered the developer's real
    ~/OpenWorker with per-session junk folders (dozens of them, found 2026-08-05 while giving
    Chat a scratch workspace). Tests that assert the shipped default compare against
    SessionManager.DEFAULT_SCRATCH_BASE rather than the literal."""
    from coworker.server.manager import SessionManager

    monkeypatch.setattr(
        SessionManager, "DEFAULT_SCRATCH_BASE", str(tmp_path / "scratch-base")
    )


@pytest_asyncio.fixture
async def fake_slack(monkeypatch):
    """A running FakeSlack control object; `SLACK_API_URL` is set to it for the test's duration."""
    fake = FakeSlack()
    await fake.start()
    monkeypatch.setenv("SLACK_API_URL", fake.api_url)
    try:
        yield fake
    finally:
        await fake.stop()
