---
name: pdf
description: Create PDFs, or merge, split, watermark, fill, and extract from existing PDF files. Load whenever the deliverable is a .pdf or the user asks to combine, stamp, or pull content out of PDFs.
---

# PDF files

Two distinct jobs — pick the right tool through `run_shell`:
- **Manipulate existing PDFs** (merge/split/rotate/watermark/extract): `pypdf` — already
  installed as an app dependency.
- **Generate new PDFs from scratch**: `reportlab` — install on first use.

```bash
python3 -c "import reportlab" 2>/dev/null || python3 -m pip install --user reportlab 2>/dev/null || python3 -m pip install --user --break-system-packages reportlab
```

If the source content is a document you are also producing (report, memo), prefer
authoring it as `.docx` (see the `docx` skill) and converting via
`soffice --headless --convert-to pdf` — layout quality beats hand-drawn reportlab pages.

After producing or transforming a PDF, **look at it** with `view_file` — it renders
pages to images you can see, so verify layout and page breaks visually before handing
the file over.

## Manipulating existing PDFs (pypdf)

```python
from pypdf import PdfReader, PdfWriter

# Merge
w = PdfWriter()
for src in ["a.pdf", "b.pdf"]:
    w.append(src)
w.write("merged.pdf")

# Split / select pages (0-indexed)
r = PdfReader("input.pdf")
w = PdfWriter()
for i in range(0, 3):
    w.add_page(r.pages[i])
w.write("first3.pdf")

# Rotate
page = r.pages[0]; page.rotate(90)

# Watermark / stamp (overlay one page onto another)
stamp = PdfReader("stamp.pdf").pages[0]
for page in r.pages:
    page.merge_page(stamp)

# Form fill (use a FRESH writer — reusing one from an example above fills the wrong page)
w = PdfWriter()
w.append("form.pdf")
w.update_page_form_field_values(w.pages[0], {"Name": "Alice"})
w.write("filled.pdf")

# Extract text
text = "\n".join(page.extract_text() or "" for page in r.pages)
```

Scanned PDFs have no text layer — `extract_text()` returns empty. Say so instead of
returning silence; offer page images (`pypdfium2` renders pages to PNG) as an alternative.

## Generating new PDFs (reportlab)

Use Platypus (flowables), not raw canvas, for anything document-like:

```python
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                Table, TableStyle, Image, PageBreak)
from reportlab.lib import colors

styles = getSampleStyleSheet()
doc = SimpleDocTemplate("out.pdf", pagesize=A4,
                        leftMargin=2*cm, rightMargin=2*cm,
                        topMargin=2*cm, bottomMargin=2*cm)
story = [
    Paragraph("Title", styles["Title"]),
    Spacer(1, 12),
    Paragraph("Body text with <b>inline bold</b>.", styles["BodyText"]),
    Table([["Item", "Qty"], ["Widget", "3"]],
          style=TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke)])),
]
doc.build(story)
```

- A4 for international audiences, LETTER for US — ask only if it matters to the user.
- Always verify the output opens: `python3 -c "from pypdf import PdfReader; print(len(PdfReader('out.pdf').pages))"`.
- Save into the workspace with a descriptive filename and never overwrite the user's
  source PDFs — write results to new files.
