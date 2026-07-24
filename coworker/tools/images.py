"""The `generate_image` tool — text prompt → PNG saved into the session's workspace.

Uses the image APIs of providers the user has already configured (no separate key):
OpenAI Images (`gpt-image-2`) or Gemini image models (`gemini-3.1-flash-image-preview`,
"Nano Banana 2"; `gemini-3-pro-image-preview` for 4K). Provider selection: explicit
`provider` arg → OpenAI key present → Gemini key present → error. The tool is
approval-gated (external: it spends API credits) and only registered when the session
has somewhere to write — the PNG always lands inside a writable root.

SDK imports are lazy (mirrors pdf_support.py) so engine assembly never pays for them.
"""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

import aisuite as ai

from ..secrets import SecretStore

DEFAULT_OPENAI_MODEL = "gpt-image-2"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-image-preview"

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate an image from a text prompt and save it as a PNG in the workspace. "
            "Uses the configured OpenAI (gpt-image-2) or Gemini (Nano Banana) image API "
            "with the user's existing provider key. Returns the saved file path."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What to draw — subject, style, composition, colors.",
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "Output filename (basename only, '.png' appended if missing). "
                        "Default: derived from the prompt."
                    ),
                },
                "size": {
                    "type": "string",
                    "description": (
                        "Image size, e.g. '1024x1024' (default), '1536x1024', "
                        "'1024x1536'. OpenAI only; Gemini picks its own resolution."
                    ),
                },
                "provider": {
                    "type": "string",
                    "enum": ["openai", "gemini"],
                    "description": "Force a provider; default picks whichever has a key.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Override the image model id (e.g. 'gemini-3-pro-image-preview' "
                        "for 4K). Default: the provider's current flagship."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
}


def _slug(prompt: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40]
    return s or "image"


def _safe_target(save_dir: Path, filename: Optional[str], prompt: str) -> Path:
    """Basename-only, forced .png, always inside `save_dir` (no traversal)."""
    name = Path(filename).name if filename else f"{_slug(prompt)}-{int(time.time())}.png"
    if not name.lower().endswith(".png"):
        name += ".png"
    target = (save_dir / name).resolve()
    target.relative_to(save_dir.resolve())  # raises on escape; basename makes this moot
    return target


def _openai_png(prompt: str, size: Optional[str], model: str, key: str) -> bytes:
    from openai import OpenAI

    result = OpenAI(api_key=key).images.generate(
        model=model, prompt=prompt, size=size or "1024x1024"
    )
    return base64.b64decode(result.data[0].b64_json)


def _gemini_png(prompt: str, size: Optional[str], model: str, key: str) -> bytes:
    from google import genai

    resp = genai.Client(api_key=key).models.generate_content(
        model=model, contents=prompt
    )
    for cand in resp.candidates or []:
        for part in getattr(cand.content, "parts", None) or []:
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                return data if isinstance(data, bytes) else base64.b64decode(data)
    raise RuntimeError("model returned no image data (possibly refused the prompt)")


def _resolve(
    secrets: SecretStore, provider: Optional[str]
) -> tuple[str, str, Optional[str]]:
    """→ (provider, default_model, api_key). Key resolution reuses the chat providers'
    explicit → env → SecretStore chain, so image generation needs no extra setup."""
    from ..providers.gemini_provider import resolve_api_key as gemini_key
    from ..providers.openai_provider import resolve_api_key as openai_key

    keys = {"openai": openai_key(secrets), "gemini": gemini_key(secrets)}
    name = provider or ("openai" if keys["openai"] else "gemini")
    default = DEFAULT_OPENAI_MODEL if name == "openai" else DEFAULT_GEMINI_MODEL
    return name, default, keys.get(name)


def make_image_tool(
    secrets: Optional[SecretStore] = None,
    *,
    workspace: Optional[Path] = None,
    roots: Optional[list[Any]] = None,
    generator: Optional[Callable[..., bytes]] = None,
) -> Callable[..., Any]:
    """Build the `generate_image` tool. `generator(provider, prompt, size, model, key)`
    overrides the real API call (used by tests)."""
    secrets = secrets or SecretStore()

    def _save_dir() -> Optional[Path]:
        for r in roots or []:
            if getattr(r, "writable", False):
                return Path(r.path)
        return Path(workspace) if workspace else None

    def generate_image(
        prompt: str,
        filename: Optional[str] = None,
        size: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        save_dir = _save_dir()
        if save_dir is None:
            return {"error": "no writable workspace folder to save the image into"}
        if provider not in (None, "openai", "gemini"):
            return {"error": f"unknown image provider: {provider}"}
        name, default_model, key = _resolve(secrets, provider)
        if not key:
            return {
                "error": (
                    "image generation needs an OpenAI or Gemini API key — "
                    "add one in Settings ▸ Models."
                )
            }
        mid = model or default_model
        try:
            if generator is not None:
                png = generator(name, prompt, size, mid, key)
            elif name == "openai":
                png = _openai_png(prompt, size, mid, key)
            else:
                png = _gemini_png(prompt, size, mid, key)
        except Exception as exc:  # network / SDK / content policy
            return {"error": f"image generation failed: {exc}", "provider": name}
        target = _safe_target(save_dir, filename, prompt)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png)
        return {
            "path": str(target),
            "provider": name,
            "model": mid,
            "bytes": len(png),
        }

    generate_image.__name__ = "generate_image"
    generate_image.__doc__ = _SCHEMA["function"]["description"]
    generate_image.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="generate_image",
        category="media",
        risk_level="medium",
        capabilities=["image"],
        requires_approval=True,  # external call, spends the user's API credits
    )
    generate_image.__coworker_schema__ = _SCHEMA
    return generate_image
