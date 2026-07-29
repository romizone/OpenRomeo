---
name: docx
description: Create, edit, or fill Microsoft Word documents (.docx) — reports, memos, letters, proposals, templates. Load whenever the deliverable is a Word file or the user mentions .docx.
---

# Word documents (.docx)

Produce real `.docx` files with the `python-docx` library, driven through `run_shell`.
Never fake a Word file by renaming Markdown or HTML — always generate a proper document.

## Setup (once per machine)

Check the library before first use; install only if missing:

```bash
python3 -c "import docx" 2>/dev/null || python3 -m pip install --user python-docx 2>/dev/null || python3 -m pip install --user --break-system-packages python-docx
```

## Creating a document

1. Write a short Python script (e.g. `make_doc.py`) into the workspace with `write_file`.
2. Run it with `run_shell`; save the output next to the user's other deliverables in the
   workspace, with a descriptive filename (`Q3-sales-report.docx`, not `output.docx`).
3. Verify the file exists and is non-trivial (`ls -la`), and **look at it** with
   `view_file` (renders pages to images you can see) to catch layout problems —
   broken tables, orphaned headings, runaway spacing — before handing it over.
4. Tell the user where it is (or hand it over with `send_file` when working from a
   chat channel).

Core patterns:

```python
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
doc.add_heading("Title", level=0)          # 0 = title style, 1-9 = heading levels
doc.add_paragraph("Body text.")
p = doc.add_paragraph()
p.add_run("Bold lead-in. ").bold = True
p.add_run("Normal continuation.")

table = doc.add_table(rows=1, cols=3)
table.style = "Light Grid Accent 1"
hdr = table.rows[0].cells
hdr[0].text, hdr[1].text, hdr[2].text = "Item", "Qty", "Price"
row = table.add_row().cells                # repeat per data row

doc.add_picture("chart.png", width=Inches(6))
doc.add_page_break()
doc.save("report.docx")
```

Styling rules of thumb:
- Use built-in heading levels (`add_heading`) so the document gets a real outline and
  a working table of contents; do not fake headings with bold text.
- One font family throughout; set it via `doc.styles["Normal"].font` rather than per-run.
- Keep tables narrow (≤ 5 columns) and put explanations in prose, not in cells.
- For long reports: title page → (optional TOC) → sections with heading levels 1-2.

## Working with a document the user uploaded

An uploaded `.docx`/`.odt` arrives two ways at once: its text is inlined for you to read,
and the real file is saved to disk — the turn carries `[Attached file saved at: <path>]`.
Always operate on that path with `python-docx`, never retype the text from the preview:
the preview drops styling, tables, headers, and images that the real file still has.
(`.odt` is not python-docx readable — convert first:
`soffice --headless --convert-to docx <path> --outdir .`)

## Editing an existing document

`python-docx` round-trips: open, mutate, save-as. Never overwrite the user's original —
save to a new file unless they explicitly asked for in-place edits.

```python
doc = Document("input.docx")
for p in doc.paragraphs:
    if "{{NAME}}" in p.text:               # simple template placeholder fill
        for run in p.runs:
            run.text = run.text.replace("{{NAME}}", "Alice")
doc.save("input.filled.docx")
```

Placeholders split across runs are common; when a placeholder is not found run-by-run,
join `p.text`, replace there, then write the result back into the first run and blank
the rest.

## Reading / extracting text

Prefer `python-docx` (`"\n".join(p.text for p in doc.paragraphs)` plus table cells).
Tell the user which parts (headers/footers, text boxes) plain extraction may miss.

## Converting to PDF

If the user wants a PDF of the finished document and LibreOffice is available:

```bash
soffice --headless --convert-to pdf report.docx --outdir .
```

If `soffice` is missing, say so and offer the `.docx` alone rather than a degraded PDF.
