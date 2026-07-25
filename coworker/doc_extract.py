"""Text extraction for uploaded office documents — Word/PowerPoint/Excel + OpenDocument.

Both OOXML (.docx/.pptx/.xlsx) and OpenDocument (.odt/.odp/.ods) are ZIP archives holding
XML, so a stdlib `zipfile` + `ElementTree` pass covers every format with NO new dependency
(the alternative — python-docx/pptx/openpyxl/odfpy in the core runtime — would add four
libraries and ~15MB to every desktop bundle for what is only a preview).

What this is for: the upload also lands on disk (attachments.py `persist_attachments`), so
the agent can always reopen it at full fidelity with the docx/pptx/xlsx skills. This module
only produces the inline text the MODEL reads to know what the document says — layout,
styling, images, and formulas are deliberately out of scope.

Untrusted input: every member read is capped (`MAX_MEMBER_BYTES`) and the result truncated
(`MAX_CHARS`), so a zip bomb or a pathological document can't exhaust memory or a context
window. ElementTree resolves no external entities, so XXE isn't reachable here.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Optional
from xml.etree import ElementTree as ET

MAX_MEMBER_BYTES = 8_000_000  # per XML member, decompressed
MAX_CHARS = 40_000  # inline preview ceiling
MAX_SHEETS = 20
MAX_SLIDES = 100
MAX_ROWS_PER_SHEET = 500

# Extension → the format family we know how to walk.
OOXML_EXT = {".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx", ".xlsm": "xlsx"}
ODF_EXT = {".odt": "odt", ".odp": "odp", ".ods": "ods"}
DOC_EXT = {**OOXML_EXT, **ODF_EXT}

# The MIME types browsers report for those extensions (the GUI sends one of these, but a
# few OSes report application/octet-stream — the extension is the authoritative check).
DOC_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
}

_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_SHEET_RE = re.compile(r"^xl/worksheets/sheet(\d+)\.xml$")
_CELL_REF_RE = re.compile(r"^([A-Z]+)")


def doc_kind(name: str) -> Optional[str]:
    """'docx' | 'pptx' | 'xlsx' | 'odt' | 'odp' | 'ods' for a filename, else None."""
    lowered = (name or "").lower()
    for ext, kind in DOC_EXT.items():
        if lowered.endswith(ext):
            return kind
    return None


def _local(tag: str) -> str:
    """`{namespace}name` → `name` — every format below is matched by local name, so one
    walker handles OOXML and ODF without carrying six namespace maps."""
    return tag.rsplit("}", 1)[-1]


def _read_xml(zf: zipfile.ZipFile, member: str) -> Optional[ET.Element]:
    try:
        info = zf.getinfo(member)
    except KeyError:
        return None
    if info.file_size > MAX_MEMBER_BYTES:
        return None
    try:
        with zf.open(info) as fh:
            return ET.fromstring(fh.read(MAX_MEMBER_BYTES))
    except (ET.ParseError, zipfile.BadZipFile, OSError, ValueError):
        return None


def _text_of(node: ET.Element, tags: set[str]) -> str:
    """Concatenate every descendant whose local tag is in `tags` (the leaf text runs)."""
    return "".join(n.text or "" for n in node.iter() if _local(n.tag) in tags)


def _paragraphs(root: ET.Element, para_tags: set[str], run_tags: set[str]) -> list[str]:
    out: list[str] = []
    for node in root.iter():
        if _local(node.tag) in para_tags:
            line = _text_of(node, run_tags).strip()
            if line:
                out.append(line)
    return out


def _docx(zf: zipfile.ZipFile) -> str:
    root = _read_xml(zf, "word/document.xml")
    if root is None:
        return ""
    # `w:p` = paragraph, `w:t` = text run. Table cells contain paragraphs too, so walking
    # every paragraph in document order already covers tables (one line per cell).
    return "\n".join(_paragraphs(root, {"p"}, {"t"}))


def _pptx(zf: zipfile.ZipFile) -> str:
    slides: list[tuple[int, str]] = []
    for member in zf.namelist():
        match = _SLIDE_RE.match(member)
        if not match:
            continue
        root = _read_xml(zf, member)
        if root is None:
            continue
        # `a:p` = text paragraph, `a:t` = text run (drawingml, shared with charts/tables).
        body = "\n".join(_paragraphs(root, {"p"}, {"t"}))
        slides.append((int(match.group(1)), body))
    slides.sort(key=lambda s: s[0])  # namelist order is arbitrary; slide10 before slide2
    return "\n\n".join(
        f"--- Slide {num} ---\n{body}" for num, body in slides[:MAX_SLIDES] if body
    )


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    root = _read_xml(zf, "xl/sharedStrings.xml")
    if root is None:
        return []
    return [
        _text_of(si, {"t"}) for si in root if _local(si.tag) == "si"
    ]  # index order IS the lookup table


def _xlsx(zf: zipfile.ZipFile) -> str:
    shared = _xlsx_shared_strings(zf)
    sheets: list[tuple[int, str]] = []
    for member in zf.namelist():
        match = _SHEET_RE.match(member)
        if not match:
            continue
        root = _read_xml(zf, member)
        if root is None:
            continue
        lines: list[str] = []
        for row in root.iter():
            if _local(row.tag) != "row":
                continue
            cells: list[str] = []
            for cell in row:
                if _local(cell.tag) != "c":
                    continue
                value = ""
                for child in cell:
                    tag = _local(child.tag)
                    if tag == "v":
                        value = child.text or ""
                    elif tag == "is":  # inline string
                        value = _text_of(child, {"t"})
                if cell.get("t") == "s" and value.isdigit():
                    index = int(value)
                    value = shared[index] if index < len(shared) else ""
                if value:
                    cells.append(value)
            if cells:
                lines.append("\t".join(cells))
            if len(lines) >= MAX_ROWS_PER_SHEET:
                lines.append("… (more rows — open the file with the xlsx skill)")
                break
        if lines:
            sheets.append((int(match.group(1)), "\n".join(lines)))
    sheets.sort(key=lambda s: s[0])
    return "\n\n".join(
        f"--- Sheet {num} ---\n{body}" for num, body in sheets[:MAX_SHEETS]
    )


def _odf(zf: zipfile.ZipFile, kind: str) -> str:
    root = _read_xml(zf, "content.xml")
    if root is None:
        return ""
    if kind == "ods":
        return _ods_tables(root)
    # ODF text (.odt) and presentations (.odp) live in `text:p` / `text:h`.
    lines: list[str] = []
    for node in root.iter():
        if _local(node.tag) in {"p", "h"}:
            line = "".join(node.itertext()).strip()
            if line:
                lines.append(line)
    return "\n".join(lines)


def _ods_tables(root: ET.Element) -> str:
    """Spreadsheet cells as tab-separated ROWS, mirroring the .xlsx output. A plain
    paragraph walk would emit one value per line, which destroys the row/column
    relationship the numbers only make sense in."""
    sheets: list[str] = []
    for table in root.iter():
        if _local(table.tag) != "table":
            continue
        name = next(
            (v for k, v in table.attrib.items() if _local(k) == "name"), ""
        )
        lines: list[str] = []
        for row in table.iter():
            if _local(row.tag) != "table-row":
                continue
            cells: list[str] = []
            for cell in row:
                if _local(cell.tag) not in {"table-cell", "covered-table-cell"}:
                    continue
                value = "".join(cell.itertext()).strip()
                # `number-columns-repeated` pads runs of identical cells — usually the
                # 1000-odd empty trailing cells LibreOffice writes, so only a repeat of a
                # NON-empty value is expanded (and bounded), never the empty padding.
                repeat = 1
                for key, raw in cell.attrib.items():
                    if _local(key) == "number-columns-repeated":
                        try:
                            repeat = max(1, min(int(raw), 50))
                        except ValueError:
                            repeat = 1
                cells.extend([value] * repeat if value else [""])
            while cells and not cells[-1]:  # drop trailing empties
                cells.pop()
            if cells:
                lines.append("\t".join(cells))
            if len(lines) >= MAX_ROWS_PER_SHEET:
                lines.append("… (more rows — open the file with the xlsx skill)")
                break
        if lines:
            header = f"--- Sheet {name} ---\n" if name else ""
            sheets.append(header + "\n".join(lines))
        if len(sheets) >= MAX_SHEETS:
            break
    return "\n\n".join(sheets)


def extract_text(data: bytes, name: str) -> str:
    """Best-effort plain text from an office/OpenDocument file. Returns "" when the format
    is unknown or the archive is unreadable — never raises, so a bad upload degrades to
    "no preview" instead of failing the turn."""
    kind = doc_kind(name)
    if not kind or not data:
        return ""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        return ""
    try:
        if kind == "docx":
            text = _docx(zf)
        elif kind == "pptx":
            text = _pptx(zf)
        elif kind == "xlsx":
            text = _xlsx(zf)
        else:
            text = _odf(zf, kind)
    except Exception:  # malformed archive that still opened — preview is optional
        return ""
    finally:
        zf.close()
    text = text.strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n… (truncated — open the file directly for the rest)"
    return text
