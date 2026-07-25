"""Office / OpenDocument uploads — text extraction + the attachment pipeline.

Fixtures are built by the real libraries (python-docx/pptx/openpyxl) when they're
installed, and by hand-written OOXML/ODF zips otherwise, so the suite runs everywhere
while still proving the extractor handles genuine files.
"""

from __future__ import annotations

import base64
import io
import zipfile

import pytest

from coworker.attachments import build_user_content, content_to_text, persist_attachments
from coworker.doc_extract import doc_kind, extract_text


def _data_url(data: bytes, mime: str = "application/octet-stream") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


# -- hand-built archives (no third-party deps needed) ------------------------------


def _zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buf.getvalue()


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A_NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
ODF_NS = 'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'


def _docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    return _zip({"word/document.xml": f"<w:document {W_NS}><w:body>{body}</w:body></w:document>"})


def _odf_bytes(*paragraphs: str) -> bytes:
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    return _zip({"content.xml": f"<office {ODF_NS}>{body}</office>"})


# -- doc_kind ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Report.docx", "docx"),
        ("deck.PPTX", "pptx"),
        ("budget.xlsx", "xlsx"),
        ("macros.xlsm", "xlsx"),
        ("notes.odt", "odt"),
        ("slides.odp", "odp"),
        ("sheet.ods", "ods"),
        ("photo.png", None),
        ("archive.zip", None),
        ("", None),
    ],
)
def test_doc_kind_by_extension(name, expected):
    assert doc_kind(name) == expected


# -- extraction ---------------------------------------------------------------------


def test_extract_docx_paragraphs():
    text = extract_text(_docx_bytes("Quarterly report", "Revenue grew 40%"), "r.docx")
    assert "Quarterly report" in text and "Revenue grew 40%" in text


def test_extract_odf_paragraphs():
    text = extract_text(_odf_bytes("Hello ODF", "Second line"), "notes.odt")
    assert "Hello ODF" in text and "Second line" in text


def test_extract_pptx_orders_slides_numerically():
    """namelist() order is arbitrary and lexical sorting puts slide10 before slide2."""
    members = {
        f"ppt/slides/slide{n}.xml": f"<sld {A_NS}><a:p><a:r><a:t>Slide {n} body</a:t></a:r></a:p></sld>"
        for n in (1, 2, 10)
    }
    text = extract_text(_zip(members), "deck.pptx")
    assert text.index("Slide 1 body") < text.index("Slide 2 body") < text.index("Slide 10 body")


def test_extract_xlsx_resolves_shared_strings():
    shared = f'<sst {S_NS}><si><t>Widget</t></si><si><t>Gadget</t></si></sst>'
    sheet = (
        f'<worksheet {S_NS}><sheetData>'
        '<row><c t="s"><v>0</v></c><c><v>19.5</v></c></row>'
        '<row><c t="s"><v>1</v></c><c><v>4.25</v></c></row>'
        "</sheetData></worksheet>"
    )
    text = extract_text(
        _zip({"xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": sheet}), "b.xlsx"
    )
    assert "Widget\t19.5" in text and "Gadget\t4.25" in text


def test_extract_never_raises_on_garbage():
    assert extract_text(b"not a zip at all", "x.docx") == ""
    assert extract_text(_zip({"unexpected.xml": "<a/>"}), "x.docx") == ""
    assert extract_text(b"", "x.docx") == ""
    assert extract_text(_docx_bytes("hi"), "photo.png") == ""  # unknown extension


def test_extract_truncates_huge_documents():
    from coworker.doc_extract import MAX_CHARS

    text = extract_text(_docx_bytes(*(["padding line"] * 20000)), "big.docx")
    assert len(text) <= MAX_CHARS + 200 and "truncated" in text


# -- attachment pipeline -------------------------------------------------------------


def test_doc_attachment_is_saved_and_previewed(tmp_path):
    raw = _docx_bytes("Board minutes", "Action items follow")
    att = [{"kind": "doc", "name": "Minutes.docx", "data_url": _data_url(raw)}]

    saved = persist_attachments(att, tmp_path)
    path = saved[0]["saved_path"]
    assert (tmp_path / "Minutes.docx").read_bytes() == raw  # byte-identical on disk

    parts = build_user_content("summarize this", saved)
    texts = [p["text"] for p in parts if p["type"] == "text"]
    assert texts[0] == "summarize this"
    assert f"[Attached file saved at: {path}]" in texts  # skills can reopen it
    body = next(t for t in texts if t.startswith("[Attached document:"))
    assert "Minutes.docx" in body and "Board minutes" in body


def test_doc_without_extractable_text_still_reaches_the_model(tmp_path):
    """An unreadable archive must not vanish — the model still learns the file exists
    and where it lives, which is enough for a skill to open it."""
    att = [{"kind": "doc", "name": "odd.docx", "data_url": _data_url(b"not-a-zip")}]
    parts = build_user_content("", persist_attachments(att, tmp_path))
    body = next(p["text"] for p in parts if p["text"].startswith("[Attached document:"))
    assert "no text could be extracted" in body


def test_doc_attachment_requires_a_known_extension(tmp_path):
    """The filename is authoritative (browsers mislabel .docx as octet-stream), so an
    unknown extension is rejected rather than written to disk as an opaque blob."""
    att = [{"kind": "doc", "name": "payload.bin", "data_url": _data_url(_docx_bytes("x"))}]
    assert persist_attachments(att, tmp_path)[0].get("saved_path") is None
    assert build_user_content("hi", att) == "hi"  # invalid attachment → text only
    assert not list(tmp_path.iterdir())


def test_doc_save_path_note_is_hidden_from_human_previews(tmp_path):
    """The saved-path note is model-facing metadata; titles and previews must not show it."""
    att = [{"kind": "doc", "name": "Plan.odt", "data_url": _data_url(_odf_bytes("Plan text"))}]
    parts = build_user_content("check this", persist_attachments(att, tmp_path))
    flat = content_to_text(parts)
    assert "saved at:" not in flat and "check this" in flat


def test_ods_keeps_row_structure():
    """A spreadsheet flattened to one value per line loses the row/column relationship the
    numbers only make sense in — .ods must come out tab-separated like .xlsx does."""
    T_NS = 'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
    content = (
        f"<office {ODF_NS} {T_NS}><table:table table:name='Data'>"
        "<table:table-row><table:table-cell><text:p>Produk</text:p></table:table-cell>"
        "<table:table-cell><text:p>Jumlah</text:p></table:table-cell></table:table-row>"
        "<table:table-row><table:table-cell><text:p>Widget</text:p></table:table-cell>"
        "<table:table-cell><text:p>7</text:p></table:table-cell></table:table-row>"
        # LibreOffice pads every sheet with ~1000 empty repeated cells; they must not
        # explode into a wall of tabs.
        "<table:table-row><table:table-cell table:number-columns-repeated='1024'/></table:table-row>"
        "</table:table></office>"
    )
    text = extract_text(_zip({"content.xml": content}), "book.ods")
    assert "Produk\tJumlah" in text and "Widget\t7" in text
    assert "Sheet Data" in text
    assert "\t\t\t" not in text  # empty padding dropped, not expanded


def test_real_opendocument_files_extract(tmp_path):
    """Genuine LibreOffice output — hand-built ODF can't catch a wrong element path that
    a real writer produces differently (skipped when LibreOffice isn't installed)."""
    import shutil
    import subprocess

    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if not shutil.which(soffice):
        pytest.skip("LibreOffice not installed")
    docx = pytest.importorskip("docx")

    d = docx.Document()
    d.add_heading("ODF Heading", level=1)
    d.add_paragraph("ODF body sentence.")
    d.save(tmp_path / "src.docx")
    subprocess.run(
        [soffice, "--headless", "--convert-to", "odt", "--outdir", str(tmp_path), str(tmp_path / "src.docx")],
        capture_output=True,
        timeout=180,
    )
    odt = tmp_path / "src.odt"
    if not odt.exists():
        pytest.skip("LibreOffice conversion unavailable in this environment")
    text = extract_text(odt.read_bytes(), "src.odt")
    assert "ODF Heading" in text and "ODF body sentence." in text


def test_doc_without_a_workspace_does_not_point_at_a_path(tmp_path):
    """With no writable root nothing is persisted, so the model must not be told to open
    a file that was never written."""
    att = [{"kind": "doc", "name": "odd.docx", "data_url": _data_url(b"not-a-zip")}]
    parts = build_user_content("", att)  # note: NOT persisted
    body = next(p["text"] for p in parts if p["text"].startswith("[Attached document:"))
    assert "not saved to disk" in body


def test_opendocument_and_xlsm_are_listed_as_artifacts(tmp_path, monkeypatch):
    """Uploads land in the session scratch dir the Artifacts rail scans — an extension
    missing from the allowlist makes the user's own upload invisible."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    from coworker.server.manager import SessionManager, _artifact_kind

    workspace = tmp_path / "ws"
    workspace.mkdir()
    for name in ("a.odt", "b.ods", "c.odp", "d.xlsm"):
        (workspace / name).write_bytes(b"x")
    mgr = SessionManager(data_dir=tmp_path, workspace=str(workspace))
    listed = {a["name"] for a in mgr.list_artifacts("no-such-session")}
    assert {"a.odt", "b.ods", "c.odp", "d.xlsm"} <= listed
    assert _artifact_kind(tmp_path / "d.xlsm") == "sheet"
    assert _artifact_kind(tmp_path / "a.odt") == "office"


def test_real_office_files_extract(tmp_path):
    """Genuine files from the libraries the document skills use — the hand-built zips
    above can't catch a wrong element path that real writers produce differently."""
    docx = pytest.importorskip("docx")
    pptx = pytest.importorskip("pptx")
    openpyxl = pytest.importorskip("openpyxl")

    d = docx.Document()
    d.add_heading("Real Heading", level=1)
    d.add_paragraph("Real body paragraph.")
    d.save(tmp_path / "real.docx")
    text = extract_text((tmp_path / "real.docx").read_bytes(), "real.docx")
    assert "Real Heading" in text and "Real body paragraph." in text

    p = pptx.Presentation()
    slide = p.slides.add_slide(p.slide_layouts[1])
    slide.shapes.title.text = "Real Slide Title"
    slide.placeholders[1].text = "Real bullet"
    p.save(tmp_path / "real.pptx")
    text = extract_text((tmp_path / "real.pptx").read_bytes(), "real.pptx")
    assert "Real Slide Title" in text and "Real bullet" in text

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Item", "Qty"])
    ws.append(["Widget", 3])
    wb.save(tmp_path / "real.xlsx")
    text = extract_text((tmp_path / "real.xlsx").read_bytes(), "real.xlsx")
    assert "Item\tQty" in text and "Widget\t3" in text
