"""The `view_file` tool — render a workspace file to page images the model can SEE.

Closes the "I built the deck but can't look at it" gap: after a skill produces a
deliverable (pptx/docx/xlsx/pdf/…), the agent calls `view_file` and the engine attaches
the rendered pages as ordinary vision input on the next model call (`_record_result`
lifts the `_view_images` sidecar into a follow-up user message; the existing
`_outbound_messages` gating swaps them for a placeholder on non-vision models).

PDFs and plain images render locally (pypdfium2 / raw bytes — no new dependency).
Office and OpenDocument formats are converted to PDF first through a headless
LibreOffice (`soffice`) when one is installed, using a throwaway profile dir so a
running desktop LibreOffice never blocks the convert. No LibreOffice → a clear error
that tells the user what to install.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

import aisuite as ai

# Rendered pages per call: enough to eyeball a deck section without flooding the
# context; the result's `note` says how to page through the rest.
DEFAULT_PAGES = 4
MAX_PAGES = 8
SOFFICE_TIMEOUT = 180  # cold LibreOffice start + a big deck can take a while
MAX_IMAGE_BYTES = 8_000_000  # direct image reads; keeps the data URL under the
# server's MAX_IMAGE_CHARS cap (attachments.py)

# Direct passthrough: types every provider path already accepts as vision input.
IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# Everything LibreOffice can turn into a PDF for us.
OFFICE_EXTS = {
    ".pptx", ".ppt", ".odp",
    ".docx", ".doc", ".odt", ".rtf",
    ".xlsx", ".xls", ".ods", ".csv",
    ".svg", ".html", ".htm",
}

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "view_file",
        "description": (
            "Look at a file with your own eyes: renders a document to page images you "
            "receive as vision input on the next turn. Use it to visually verify a "
            "deliverable you produced (pptx, docx, xlsx, pdf, …) or to inspect an "
            "image/diagram in the workspace. PDFs and images render locally; Office "
            "formats need LibreOffice installed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File to view, inside the session's folders.",
                },
                "pages": {
                    "type": "string",
                    "description": (
                        "1-based page/slide range, e.g. '3' or '2-5'. "
                        f"Default: first {DEFAULT_PAGES}; at most {MAX_PAGES} per call."
                    ),
                },
            },
            "required": ["path"],
        },
    },
}


def _find_soffice() -> Optional[str]:
    import shutil

    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "C:\\Program Files\\LibreOffice\\program\\soffice.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _soffice_convert(target: Path) -> bytes:
    """`target` → PDF bytes via headless LibreOffice. Raises RuntimeError with a
    user-actionable message on any failure."""
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError(
            f"rendering {target.suffix} needs LibreOffice, which isn't installed — "
            "get it from libreoffice.org (macOS: `brew install --cask libreoffice`). "
            "PDFs and images render without it."
        )
    with tempfile.TemporaryDirectory(prefix="coworker-view-") as tmp:
        profile = Path(tmp) / "profile"  # throwaway → no clash with a running desktop LO
        outdir = Path(tmp) / "out"
        proc = subprocess.run(
            [
                soffice,
                "--headless",
                "--norestore",
                f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(target),
            ],
            capture_output=True,
            timeout=SOFFICE_TIMEOUT,
        )
        pdfs = list(outdir.glob("*.pdf")) if outdir.exists() else []
        if not pdfs:
            detail = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
            raise RuntimeError(
                f"LibreOffice could not convert {target.name} to PDF"
                + (f": {detail[-300:]}" if detail else "")
            )
        return pdfs[0].read_bytes()


def _parse_pages(spec: Optional[str]) -> Optional[tuple[int, int]]:
    """'3' / '2-5' → 1-based inclusive (start, end), window clamped to MAX_PAGES.
    None on a malformed spec."""
    if not spec:
        return (1, DEFAULT_PAGES)
    text = str(spec).strip()
    first, _, second = text.partition("-")
    try:
        start = int(first)
        end = int(second) if second else start
    except ValueError:
        return None
    if start < 1 or end < start:
        return None
    return (start, min(end, start + MAX_PAGES - 1))


def make_view_file_tool(
    *,
    workspace: Optional[Path] = None,
    roots: Optional[list[Any]] = None,
    converter: Optional[Callable[[Path], bytes]] = None,
) -> Callable[..., Any]:
    """Build the `view_file` tool. `converter(path) -> pdf bytes` overrides the
    LibreOffice call (used by tests)."""

    def _dirs() -> list[Path]:
        dirs = [Path(workspace).resolve()] if workspace else []
        for root in roots or []:
            path = Path(getattr(root, "path", root)).resolve()
            if path not in dirs:
                dirs.append(path)
        return dirs

    def view_file(path: str, pages: Optional[str] = None) -> dict[str, Any]:
        dirs = _dirs()
        if not dirs:
            return {"error": "no session folders to read from"}
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = dirs[0] / target
        target = target.resolve()
        if not any(target.is_relative_to(d) for d in dirs):
            return {"error": f"{path} is outside the session's folders"}
        if not target.is_file():
            return {"error": f"file not found: {path}"}

        window = _parse_pages(pages)
        if window is None:
            return {"error": f"bad pages spec {pages!r} — use e.g. '3' or '2-5'"}

        suffix = target.suffix.lower()
        if suffix in IMAGE_MIMES:
            raw = target.read_bytes()
            if len(raw) > MAX_IMAGE_BYTES:
                return {"error": f"{target.name} is too large to view (>8MB)"}
            import base64

            url = f"data:{IMAGE_MIMES[suffix]};base64," + base64.b64encode(raw).decode()
            return {
                "path": str(target),
                "total_pages": 1,
                "pages_shown": [1],
                "note": "image attached — you will see it on your next turn",
                "_view_images": [url],
            }

        if suffix == ".pdf":
            pdf_raw = target.read_bytes()
        elif suffix in OFFICE_EXTS:
            try:
                pdf_raw = converter(target) if converter else _soffice_convert(target)
            except subprocess.TimeoutExpired:
                return {"error": f"LibreOffice timed out converting {target.name}"}
            except RuntimeError as exc:
                return {"error": str(exc)}
        else:
            return {
                "error": (
                    f"cannot render {suffix or 'that file'} — supported: pdf, "
                    "images (png/jpg/gif/webp), and Office/OpenDocument formats"
                )
            }

        from .. import pdf_support

        start, end = window
        rendered = pdf_support.render_pdf_pages(pdf_raw, list(range(start - 1, end)))
        if rendered is None:
            return {"error": f"could not render {target.name} (broken or empty document)"}
        urls, total = rendered
        shown = list(range(start, start + len(urls)))
        note = f"pages {shown[0]}–{shown[-1]} of {total} attached — you will see them on your next turn"
        if total > shown[-1]:
            note += f"; call again with pages='{shown[-1] + 1}-{min(shown[-1] + MAX_PAGES, total)}' for more"
        return {
            "path": str(target),
            "total_pages": total,
            "pages_shown": shown,
            "note": note,
            "_view_images": urls,
        }

    view_file.__name__ = "view_file"
    view_file.__doc__ = _SCHEMA["function"]["description"]
    view_file.__aisuite_tool_metadata__ = ai.ToolMetadata(
        name="view_file",
        category="files",
        risk_level="low",  # local read + render; nothing leaves the machine here
        capabilities=["read"],
        requires_approval=False,
    )
    view_file.__coworker_schema__ = _SCHEMA
    return view_file
