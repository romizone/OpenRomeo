"""Phase 1 gate — persona registry lifecycle (installed → enabled → surfaced + default)."""

from __future__ import annotations

import pytest

from coworker.personas.registry import DEFAULT_PERSONA_ID, PersonaRegistry


def _reg(tmp_path) -> PersonaRegistry:
    return PersonaRegistry(state_path=tmp_path / "personas.json")


def test_builtins_present(tmp_path):
    reg = _reg(tmp_path)
    assert {"code", "chat", "cowork", "ops"} <= set(reg.ids())
    assert reg.get("ops").builtin is True
    # Ops came from a markdown manifest; Code from a builder.
    assert reg.get("ops").manifest is not None
    assert reg.get("code").manifest is None


def test_sidebar_defaults_to_cowork_and_chat(tmp_path):
    reg = _reg(tmp_path)
    sidebar = reg.sidebar()
    ids = [e["name"] for e in sidebar]
    # A fresh install offers OpenWorker (the default persona) plus OpenChat (the
    # direct-chat surface); everything else is opt-in from Settings ▸ Personas.
    assert ids == ["cowork", "chat"]
    assert sidebar[0]["default"] is True
    # Enabling adds to the picker (enable implies surface).
    reg.set_enabled("code", True)
    reg.set_enabled("ops", True)
    ids = [e["name"] for e in reg.sidebar()]
    assert ids[0] == "cowork"
    assert set(ids) == {"cowork", "chat", "code", "ops"}


def test_chat_enabled_by_default_and_dismissable(tmp_path):
    reg = _reg(tmp_path)
    assert reg.is_surfaced("chat") is True  # OpenChat ships visible
    assert reg.is_enabled("chat") is True
    assert reg.get("chat").name == "OpenChat"
    assert reg.agent("chat").name == "chat"
    # An explicit user choice still wins: disabling removes it from the picker…
    reg.set_enabled("chat", False)
    assert "chat" not in [e["name"] for e in reg.sidebar()]
    # …while live sessions keep resolving.
    assert reg.agent("chat").name == "chat"


def test_surface_toggle_filters_picker_but_keeps_resolvable(tmp_path):
    reg = _reg(tmp_path)
    reg.set_surfaced("ops", False)
    assert "ops" not in [e["name"] for e in reg.sidebar()]
    # Still installed + still resolvable (a session already on Ops keeps working).
    assert "ops" in reg.ids()
    assert reg.agent("ops").name == "ops"
    assert any(p["id"] == "ops" and not p["surfaced"] for p in reg.list_all())


def test_disable_default_falls_back(tmp_path):
    reg = _reg(tmp_path)
    assert reg.default_id() == DEFAULT_PERSONA_ID  # cowork
    reg.set_enabled("ops", True)  # another persona must be enabled to fall back to
    reg.set_enabled("cowork", False)
    # Cowork off → default resolves to another enabled persona, not cowork.
    assert reg.default_id() != "cowork"
    # Unknown / unspecified persona falls back to the (new) default, which is enabled.
    fallback = reg.agent(None)
    assert reg.is_enabled(fallback.name)


def test_set_default_enables_and_persists(tmp_path):
    reg = _reg(tmp_path)
    reg.set_default("ops")
    assert reg.default_id() == "ops" and reg.is_enabled("ops")
    # New instance reads persisted state.
    reg2 = _reg(tmp_path)
    assert reg2.default_id() == "ops"


def test_agent_resolution(tmp_path):
    reg = _reg(tmp_path)
    assert reg.agent("ops").family == "knowledge"
    assert reg.agent("code").family == "code"
    # Unknown id → default persona.
    assert reg.agent("does-not-exist").name == reg.default_id()


def test_list_all_carries_workspace_enum(tmp_path):
    # Post-§16 collapse: workspace derives from family — code → git, knowledge → deliverable
    # (scratch). Only builder-registered Chat keeps "none". Ops is a scratch persona now.
    reg = _reg(tmp_path)
    ws = {p["id"]: p["workspace"] for p in reg.list_all()}
    assert ws["code"] == "git"
    assert ws["cowork"] == "deliverable"
    assert ws["chat"] == "none"
    assert ws["ops"] == "deliverable"


def test_set_unknown_persona_raises(tmp_path):
    reg = _reg(tmp_path)
    with pytest.raises(KeyError):
        reg.set_enabled("ghost", False)
