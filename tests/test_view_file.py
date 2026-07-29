"""`view_file` (tools/preview.py) + the engine's preview flush — all local, no
LibreOffice: office conversion is exercised through the `converter` override."""

from __future__ import annotations

import asyncio
import base64
import io

from coworker.engine import TurnEngine
from coworker.permissions import PermissionEngine
from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    ToolCall,
)
from coworker.tools import ToolRegistry
from coworker.tools import preview as preview_mod
from coworker.tools.preview import make_view_file_tool

# 1×1 red pixel
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842"
    "iQAAAABJRU5ErkJggg=="
)


def _tiny_pdf(pages: int = 3) -> bytes:
    import pypdfium2

    doc = pypdfium2.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 100)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _tool(tmp_path, **kwargs):
    return make_view_file_tool(workspace=tmp_path, **kwargs)


# -- rendering ------------------------------------------------------------------


def test_renders_pdf_pages(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(_tiny_pdf(3))
    result = _tool(tmp_path)("doc.pdf")
    assert result["total_pages"] == 3
    assert result["pages_shown"] == [1, 2, 3]
    assert len(result["_view_images"]) == 3
    assert all(u.startswith("data:image/png;base64,") for u in result["_view_images"])


def test_pages_window_and_note(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(_tiny_pdf(3))
    result = _tool(tmp_path)("doc.pdf", pages="2")
    assert result["pages_shown"] == [2]
    assert "of 3" in result["note"]


def test_default_window_caps_and_suggests_next(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(_tiny_pdf(6))
    result = _tool(tmp_path)("doc.pdf")
    assert result["pages_shown"] == [1, 2, 3, 4]
    assert "pages='5-" in result["note"]


def test_bad_pages_spec(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(_tiny_pdf(1))
    assert "error" in _tool(tmp_path)("doc.pdf", pages="x-y")
    assert "error" in _tool(tmp_path)("doc.pdf", pages="5-2")


def test_image_passthrough(tmp_path):
    (tmp_path / "shot.png").write_bytes(PNG_1PX)
    result = _tool(tmp_path)("shot.png")
    assert result["total_pages"] == 1
    assert result["_view_images"][0].startswith("data:image/png;base64,")


# -- safety ---------------------------------------------------------------------


def test_path_stays_inside_session_folders(tmp_path):
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(_tiny_pdf(1))
    ws = tmp_path / "ws"
    ws.mkdir()
    assert "outside" in _tool(ws)(str(outside))["error"]
    assert "outside" in _tool(ws)("../outside.pdf")["error"]


def test_missing_file_and_unsupported_type(tmp_path):
    assert "not found" in _tool(tmp_path)("nope.pdf")["error"]
    (tmp_path / "a.zip").write_bytes(b"PK")
    assert "supported" in _tool(tmp_path)("a.zip")["error"]


def test_metadata_is_local_low_risk():
    meta = _tool(None, roots=None).__aisuite_tool_metadata__
    assert meta.risk_level == "low"
    assert meta.requires_approval is False


# -- office conversion ----------------------------------------------------------


def test_office_renders_via_converter(tmp_path):
    (tmp_path / "deck.pptx").write_bytes(b"not really a pptx")
    seen = []

    def converter(path):
        seen.append(path.name)
        return _tiny_pdf(2)

    result = _tool(tmp_path, converter=converter)("deck.pptx")
    assert seen == ["deck.pptx"]
    assert result["total_pages"] == 2
    assert len(result["_view_images"]) == 2


def test_office_without_soffice_says_what_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(preview_mod, "_find_soffice", lambda: None)
    (tmp_path / "deck.pptx").write_bytes(b"x")
    assert "LibreOffice" in _tool(tmp_path)("deck.pptx")["error"]


# -- engine flush ---------------------------------------------------------------


class _ScriptedProvider(ProviderClient):
    def __init__(self, turns):
        self._turns = list(turns)

    def complete(self, *, model, messages, tools=None, **settings):
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities(vision=True)


def test_engine_lifts_view_images_into_a_preview_message(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(_tiny_pdf(2))
    provider = _ScriptedProvider(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(id="c1", name="view_file", arguments={"path": "doc.pdf"})
                ],
                finish_reason="tool_calls",
            ),
            AssistantTurn(text="looks good", finish_reason="stop"),
        ]
    )
    registry = ToolRegistry()
    registry.register(make_view_file_tool(workspace=tmp_path))
    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="m",
    )

    async def _run():
        return [ev async for ev in engine.run("check the doc")]

    asyncio.run(_run())

    tool_msgs = [m for m in engine.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    # The result the model READS carries no base64 payload…
    import json

    recorded = json.loads(tool_msgs[0]["content"])
    assert "_view_images" not in recorded
    assert "data:image/png" not in tool_msgs[0]["content"]
    # …the pages arrive as a follow-up user message with ordinary image parts.
    previews = [
        m
        for m in engine.messages
        if m.get("role") == "user" and (m.get("source") or {}).get("kind") == "tool_preview"
    ]
    assert len(previews) == 1
    images = [p for p in previews[0]["content"] if p.get("type") == "image_url"]
    assert len(images) == 2
    assert images[0]["image_url"]["url"].startswith("data:image/png;base64,")
    # And the preview message lands after the tool result, keeping pairing intact.
    assert engine.messages.index(previews[0]) > engine.messages.index(tool_msgs[0])
    assert engine._pending_previews == []
