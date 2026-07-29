---
name: xlsx
description: Create, edit, or analyze Excel spreadsheets (.xlsx) — reports, budgets, data tables, dashboards. Load whenever the deliverable is a spreadsheet or the user mentions .xlsx, Excel, or CSV-to-spreadsheet work.
---

# Spreadsheets (.xlsx)

Produce real `.xlsx` files with the `openpyxl` library, driven through `run_shell`.
Never fake a spreadsheet by renaming a CSV — formulas, formatting, and multiple
sheets need a real workbook.

## Setup (once per machine)

```bash
python3 -c "import openpyxl" 2>/dev/null || python3 -m pip install --user openpyxl 2>/dev/null || python3 -m pip install --user --break-system-packages openpyxl
```

## Creating a workbook

1. Write a short Python script into the workspace with `write_file`, run it with `run_shell`.
2. Save with a descriptive filename (`2026-budget.xlsx`, not `output.xlsx`).
3. Verify it opens (`openpyxl.load_workbook`); for formatted sheets, `view_file`
   renders the workbook to images you can see — check column widths, number formats,
   and chart placement visually. Then tell the user where it landed.

Core patterns:

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, numbers
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "Summary"

ws.append(["Item", "Qty", "Unit price", "Total"])          # header row
for cell in ws[1]:
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill("solid", fgColor="1F4E79")

rows = [["Widget", 3, 19.5], ["Gadget", 7, 4.25]]
for r, (name, qty, price) in enumerate(rows, start=2):
    ws.append([name, qty, price, f"=B{r}*C{r}"])           # real Excel formula

ws.append(["", "", "Grand total", f"=SUM(D2:D{len(rows)+1})"])
for col in ("C", "D"):                                     # currency format
    for cell in ws[col][1:]:
        cell.number_format = numbers.FORMAT_CURRENCY_USD_SIMPLE

for i, _ in enumerate(ws.columns, 1):                      # readable widths
    ws.column_dimensions[get_column_letter(i)].width = 16

ws.freeze_panes = "A2"                                     # sticky header
wb.create_sheet("Raw data")                                # extra sheets as needed
wb.save("report.xlsx")
```

Spreadsheet rules of thumb:
- **Formulas over baked values** whenever a cell derives from others — the user will
  edit the inputs and expect totals to follow. openpyxl stores the formula string;
  Excel computes it on open.
- One table per sheet, headers bold + frozen, no merged cells inside data ranges.
- Set `number_format` (currency, percent `0.0%`, dates `yyyy-mm-dd`) — raw floats in
  a money column read as sloppy work.
- Charts when asked: `openpyxl.chart.BarChart` / `LineChart` / `PieChart` anchored to
  a cell (`ws.add_chart(chart, "F2")`).

## Working with a workbook the user uploaded

An uploaded `.xlsx`/`.ods` arrives twice: a text preview you can read inline, and the real
file on disk — the turn carries `[Attached file saved at: <path>]`. Open that path with
`openpyxl` for anything real; the preview is truncated (500 rows/sheet) and carries no
formulas or formats. (`.ods` is not openpyxl-readable — convert first:
`soffice --headless --convert-to xlsx <path> --outdir .`)

## Editing an existing workbook

```python
from openpyxl import load_workbook
wb = load_workbook("input.xlsx")          # keep formulas intact
ws = wb["Sheet1"]
ws["B7"] = 42
wb.save("input.updated.xlsx")             # never clobber the original unasked
```

`load_workbook(..., data_only=True)` reads the **last computed values** instead of
formulas — use it for analysis, but never save from it (formulas would be lost).

## Reading / analyzing

Iterate `ws.iter_rows(values_only=True)` for data; summarize in chat with the numbers
that matter. Note that `data_only=True` returns `None` for formula cells if the file
was never opened in Excel — say so instead of reporting empty data.

## CSV in, spreadsheet out

Read the CSV with Python's `csv` module, then apply the creation patterns above
(header styling, number formats, formulas). Keep the raw CSV untouched.
