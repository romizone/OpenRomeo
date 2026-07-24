"""`generate_image` tool — provider resolution, path confinement, engine wiring."""

from __future__ import annotations

from coworker.agent import build_engine
from coworker.agents import chat_agent, code_agent
from coworker.providers import ModelCapabilities
from coworker.tools import ToolRegistry
from coworker.tools.images import make_image_tool

PNG = b"\x89PNG\r\n\x1a\nfakebytes"


class _Stub:
    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()


class _Secrets:
    """SecretStore stand-in: only an OpenAI key is configured."""

    def __init__(self, profiles=None):
        self._profiles = profiles or {"provider:openai": {"api_key": "sk-test"}}

    def get(self, name):
        return self._profiles.get(name)

    def resolve(self, name, field):  # openai/gemini resolve_api_key fallback path
        profile = self._profiles.get(name) or {}
        return profile.get(field)


def _tool(tmp_path, secrets=None, generator=None):
    return make_image_tool(
        secrets or _Secrets(), workspace=tmp_path, generator=generator
    )


def test_generates_and_saves_png(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls = {}

    def fake_gen(provider, prompt, size, model, key):
        calls.update(provider=provider, prompt=prompt, model=model, key=key)
        return PNG

    out = _tool(tmp_path, generator=fake_gen)(prompt="a red fox, watercolor")
    assert "error" not in out
    assert calls["provider"] == "openai" and calls["model"] == "gpt-image-2"
    saved = tmp_path / out["path"].split("/")[-1]
    assert saved.read_bytes() == PNG and out["bytes"] == len(PNG)
    assert out["path"].endswith(".png") and "red-fox" in out["path"]


def test_filename_is_confined_to_workspace(tmp_path):
    out = _tool(tmp_path, generator=lambda *a: PNG)(
        prompt="x", filename="../../evil"
    )
    saved = tmp_path / "evil.png"  # basename only, .png forced, inside the workspace
    assert saved.exists() and out["path"] == str(saved)


def test_no_key_yields_helpful_error(tmp_path, monkeypatch):
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    out = _tool(tmp_path, secrets=_Secrets(profiles={}))(prompt="x")
    assert "API key" in out["error"]


def test_unknown_provider_rejected(tmp_path):
    out = _tool(tmp_path, generator=lambda *a: PNG)(prompt="x", provider="dalle")
    assert "unknown image provider" in out["error"]


def test_metadata_gates_approval():
    tool = make_image_tool(_Secrets(), workspace=None)
    meta = tool.__aisuite_tool_metadata__
    assert meta.requires_approval is True  # EXTERNAL: spends the user's credits
    reg = ToolRegistry()
    reg.register(tool)
    assert "generate_image" in reg.names()


def test_engine_wiring_workspace_only(tmp_path):
    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        assert "generate_image" in engine.registry.names()
    finally:
        engine.executor.close()
    chat = build_engine(agent=chat_agent(), provider=_Stub())
    assert "generate_image" not in chat.registry.names()
