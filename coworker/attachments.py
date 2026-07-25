"""Build OpenAI content-parts from a user message + attachments (images, PDFs, text files).

We pass messages straight to the OpenAI SDK, which accepts `content` as either a string or an
array of parts: `{"type": "text", ...}`, `{"type": "image_url", "image_url": {"url": ...}}`
(data: URLs work, and vision models read them), and `{"type": "file", "file": {"filename",
"file_data"}}` for PDFs. So image/PDF attachments are just parts appended to the user turn —
the Anthropic/Gemini providers convert them to their own block shapes.

`build_user_content` returns a plain string when there are no attachments (back-compat with the
text-only path), else the parts list.
"""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any, Optional

MAX_ATTACHMENTS = 8
MAX_IMAGE_CHARS = 12_000_000  # data-URL length cap (~8–9 MB decoded); keeps a turn sane
MAX_PDF_CHARS = 15_000_000  # data-URL length cap (~10 MB decoded, the GUI's pick limit)
MAX_DOC_CHARS = 15_000_000  # office/OpenDocument uploads, same ~10 MB decoded ceiling
MAX_TEXT_CHARS = 200_000  # per text file, inlined

# data:image/<subtype> → file extension for saved uploads (persist_attachments).
_IMAGE_EXT = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "gif": ".gif", "webp": ".webp", "svg+xml": ".svg"}

# The saved-path notes are for the MODEL (they carry the path a skill script can embed);
# human-facing flattenings (session titles, previews — content_to_text) and the GUI
# transcript skip them. A note is always a standalone single-line part, so match one line
# only — NOT DOTALL: a multi-line user message that merely opens like a note must not be
# swallowed. itemsFromMessages.ts mirrors this regex — keep the two in sync.
_UPLOAD_NOTE = re.compile(r"^\[Attached (?:image|PDF|file) saved at: [^\n]*\]$")

# Persisted text uploads are capped well above the message-inline cap (a skill may want to
# read more than the model is shown) but still bounded — an uncapped write is a disk-fill DoS.
MAX_TEXT_PERSIST_CHARS = 5_000_000


def _is_data_image(url: Any) -> bool:
    return isinstance(url, str) and url.startswith("data:image/") and ";base64," in url


def _is_data_pdf(url: Any) -> bool:
    return isinstance(url, str) and url.startswith("data:application/pdf;base64,")


def _is_data_doc(url: Any, name: Any) -> bool:
    """Office/OpenDocument upload: any base64 data URL whose FILENAME carries a known
    extension. The extension is authoritative because browsers report these inconsistently
    (Windows often sends application/octet-stream for .docx), and the data URL's own MIME
    is attacker-controlled anyway — doc_extract re-validates by actually opening the ZIP."""
    from .doc_extract import doc_kind

    return (
        isinstance(url, str)
        and url.startswith("data:")
        and ";base64," in url
        and doc_kind(str(name or "")) is not None
    )


# -- saving uploads to disk -------------------------------------------------------
# The model sees an uploaded image only as vision input — it cannot re-emit the bytes,
# so a skill script (`doc.add_picture(...)`) has nothing to point at unless the upload
# also lands as a real file. `persist_attachments` writes each valid attachment into the
# session's writable root and tags it with `saved_path`; `build_user_content` then tells
# the model where the file lives, right next to the part the model perceives.


def _safe_name(name: Any, fallback: str) -> str:
    """Basename only, cross-platform-safe characters, never hidden/dot-relative.

    Order matters: strip whitespace FIRST, then the dots — `" ."` would otherwise survive
    `lstrip(".")` untouched and re-emerge as `"."`, which resolves back to the save dir.
    """
    base = Path(str(name or "")).name if name else ""
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", base).strip().lstrip(".").strip()
    if base in {"", ".", ".."}:
        return fallback
    return base


def _unique(target: Path) -> Path:
    """First free `name.ext`, `name-1.ext`, `name-2.ext`, … under target's parent."""
    if not target.exists():
        return target
    for i in range(1, 1000):
        candidate = target.with_name(f"{target.stem}-{i}{target.suffix}")
        if not candidate.exists():
            return candidate
    return target.with_name(f"{target.stem}-{int(time.time())}{target.suffix}")


def _decode_data_url(url: str) -> Optional[bytes]:
    try:
        return base64.b64decode(url.split(";base64,", 1)[1])
    except Exception:
        return None


def persist_attachments(
    attachments: Optional[list[dict]], save_dir: Any
) -> Optional[list[dict]]:
    """Write valid attachments into `save_dir`; return a new list where each written
    entry carries `saved_path` (absolute str). Entries that fail validation (same rules
    as `build_user_content`) or fail to write pass through unchanged — this never raises,
    so the turn always proceeds at least as well as without persistence.
    """
    if not attachments or not save_dir:
        return attachments
    save_dir = Path(save_dir)
    out: list[dict] = list(attachments)
    for i, a in enumerate(attachments[:MAX_ATTACHMENTS]):
        if not isinstance(a, dict):
            continue
        kind, data = a.get("kind"), None
        if kind == "image":
            url = a.get("data_url") or ""
            if not (_is_data_image(url) and len(url) <= MAX_IMAGE_CHARS):
                continue
            subtype = url[len("data:image/") :].split(";", 1)[0].lower()
            ext = _IMAGE_EXT.get(subtype, ".png")
            data = _decode_data_url(url)
            name = _safe_name(a.get("name"), f"upload-{int(time.time())}{ext}")
            if not Path(name).suffix:
                name += ext
        elif kind == "pdf":
            url = a.get("data_url") or ""
            if not (_is_data_pdf(url) and len(url) <= MAX_PDF_CHARS):
                continue
            data = _decode_data_url(url)
            name = _safe_name(a.get("name"), "attachment.pdf")
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
        elif kind == "doc":
            url = a.get("data_url") or ""
            if not (_is_data_doc(url, a.get("name")) and len(url) <= MAX_DOC_CHARS):
                continue
            data = _decode_data_url(url)
            name = _safe_name(a.get("name"), "attachment.docx")
        elif kind == "text":
            body = str(a.get("text") or "")[:MAX_TEXT_PERSIST_CHARS]
            if not body:
                continue
            # `surrogatepass`: ws.receive_json happily yields lone surrogates ("\ud800"),
            # which plain utf-8 refuses — and this runs before the try, so a raise here
            # would tear down the socket instead of just skipping the file.
            data = body.encode("utf-8", "surrogatepass")
            name = _safe_name(a.get("name"), "attachment.txt")
        else:
            continue
        if data is None:
            continue
        try:
            target = (save_dir / name).resolve()
            target = _unique(target)
            # Verify containment AFTER _unique — `_unique` re-targets via `with_name`,
            # which for a target equal to save_dir itself would point at its parent.
            if target.parent != save_dir.resolve():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except Exception:
            continue  # disk full / permissions / race — the part still reaches the model
        out[i] = {**a, "saved_path": str(target)}
    return out


def build_user_content(
    text: Optional[str], attachments: Optional[list[dict]] = None
) -> Any:
    """Return `str` (no attachments) or a list of OpenAI content-parts (with attachments).

    Each attachment is `{"kind": "image"|"pdf"|"doc"|"text", "name"?, "data_url"?
    (image/pdf/doc), "text"? (text)}`.
    Invalid/oversized attachments are skipped rather than failing the turn.
    """
    text = (text or "").strip()
    attachments = attachments or []
    if not attachments:
        return text

    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})

    added = 0  # attachment parts that actually made it in
    for a in attachments[:MAX_ATTACHMENTS]:
        if not isinstance(a, dict):
            continue
        kind = a.get("kind")
        saved = a.get("saved_path")  # set by persist_attachments; adjacency ties the
        # note to its part, so multiple uploads each keep their own path.
        if kind == "image":
            url = a.get("data_url") or ""
            if _is_data_image(url) and len(url) <= MAX_IMAGE_CHARS:
                if saved:
                    parts.append(
                        {"type": "text", "text": f"[Attached image saved at: {saved}]"}
                    )
                parts.append({"type": "image_url", "image_url": {"url": url}})
                added += 1
        elif kind == "pdf":
            url = a.get("data_url") or ""
            if _is_data_pdf(url) and len(url) <= MAX_PDF_CHARS:
                name = str(a.get("name") or "attachment.pdf")
                if saved:
                    parts.append(
                        {"type": "text", "text": f"[Attached PDF saved at: {saved}]"}
                    )
                parts.append(
                    {"type": "file", "file": {"filename": name, "file_data": url}}
                )
                added += 1
        elif kind == "doc":
            # No provider takes .docx/.xlsx/.odt natively, so the model gets locally
            # extracted text. The file itself is on disk (saved_path), which is what lets
            # a skill reopen it at full fidelity — say so, or the model assumes the text
            # IS the document and edits a copy that never existed.
            url = a.get("data_url") or ""
            if _is_data_doc(url, a.get("name")) and len(url) <= MAX_DOC_CHARS:
                from .doc_extract import extract_text

                name = str(a.get("name") or "document")
                raw = _decode_data_url(url) or b""
                body = extract_text(raw, name)
                if saved:
                    parts.append(
                        {"type": "text", "text": f"[Attached file saved at: {saved}]"}
                    )
                header = f"[Attached document: {name}]"
                # Without `saved` (no writable root — e.g. a Chat session) the file exists
                # only as this text. Pointing the model at "the file" would send it hunting
                # for a path that was never written.
                if body:
                    text_part = f"{header}\n{body}"
                elif saved:
                    text_part = (
                        f"{header}\n(no text could be extracted — open the file at the "
                        f"path above with the matching skill)"
                    )
                else:
                    text_part = (
                        f"{header}\n(no text could be extracted, and the file was not "
                        f"saved to disk in this session — ask the user to re-send it in a "
                        f"session with a workspace folder)"
                    )
                parts.append({"type": "text", "text": text_part})
                added += 1
        elif kind == "text":
            body = str(a.get("text") or "")[:MAX_TEXT_CHARS]
            name = str(a.get("name") or "attachment")
            if body:
                # The path rides as its own note part (filtered from titles/previews like
                # the image/PDF ones); the inlined body keeps its original header, which
                # human-facing flattenings are expected to show.
                if saved:
                    parts.append(
                        {"type": "text", "text": f"[Attached file saved at: {saved}]"}
                    )
                parts.append(
                    {"type": "text", "text": f"[Attached file: {name}]\n{body}"}
                )
                added += 1

    if added == 0:
        return text  # every attachment was invalid/empty → just the text (possibly "")
    return parts


def content_to_text(content: Any, *, image_placeholder: str = "[image]") -> str:
    """Flatten message content (string or parts) to text — for titles, previews, search.
    Images render as `image_placeholder` (pass "" to drop them, e.g. for clean titles).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text = str(part.get("text", ""))
                if _UPLOAD_NOTE.match(text):
                    continue  # model-facing metadata — not part of what the user said
                out.append(text)
            elif part.get("type") == "image_url" and image_placeholder:
                out.append(image_placeholder)
            elif part.get("type") == "file" and image_placeholder:
                out.append("[pdf]")
        return " ".join(out).strip()
    return ""
