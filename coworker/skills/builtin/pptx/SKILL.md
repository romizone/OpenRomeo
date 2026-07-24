---
name: pptx
description: Create or edit PowerPoint presentations (.pptx) — pitch decks, slide reports, talk slides. Load whenever the deliverable is a slide deck or the user mentions .pptx, slides, deck, or presentation.
---

# Presentations (.pptx)

Produce real `.pptx` files with the `python-pptx` library, driven through `run_shell`.

## Setup (once per machine)

```bash
python3 -c "import pptx" 2>/dev/null || python3 -m pip install --user python-pptx
```

## Workflow

1. **Outline first.** Draft the slide list (title + 3-6 bullets each) in your reply and
   sanity-check it against what the user asked for before generating anything.
2. Write a Python script into the workspace with `write_file`, run it with `run_shell`.
3. Verify the file exists, then hand it over (path in the workspace, or `send_file`).

## Core patterns

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)   # 16:9 — always

# Title slide (layout 0), then title+content (layout 1)
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = "Deck title"
slide.placeholders[1].text = "Subtitle · date"

s = prs.slides.add_slide(prs.slide_layouts[1])
s.shapes.title.text = "Section point"
body = s.placeholders[1].text_frame
body.text = "First bullet"
for line in ["Second bullet", "Third bullet"]:
    para = body.add_paragraph()
    para.text = line
    para.level = 0                       # 1 = sub-bullet

s.notes_slide.notes_text_frame.text = "Speaker notes go here."

pic = s.shapes.add_picture("chart.png", Inches(7), Inches(1.5), width=Inches(5.5))
prs.save("deck.pptx")
```

Tables: `shapes.add_table(rows, cols, left, top, width, height)`; charts:
`shapes.add_chart` with `CategoryChartData` — prefer a pre-rendered PNG when the chart
is complex, native chart objects when the user will edit numbers later.

## Design rules

- 16:9 unless the user says otherwise. One idea per slide.
- ≤ 6 bullets per slide, ≤ ~10 words per bullet; move detail to speaker notes.
- Titles are conclusions ("Revenue grew 40% in Q3"), not labels ("Revenue").
- Consistency: same title position, font family, and color accents on every slide.
  Dark text on light background (or the reverse) — check contrast when coloring.
- Leave whitespace; do not fill every slide edge-to-edge.

## Editing an existing deck

Open with `Presentation("input.pptx")`, mutate shapes/placeholders, save to a NEW file
(never clobber the user's original without being asked). To reuse a corporate template,
open the template file and `add_slide` from its layouts so branding carries over.

## Reading a deck

Extract text with `python-pptx` by walking `slide.shapes` and reading `.text_frame.text`
(note: grouped shapes and images with text are not extracted — say so when summarizing).
