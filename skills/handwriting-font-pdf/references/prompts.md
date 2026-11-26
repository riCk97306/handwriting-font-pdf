# Copy-Paste Prompt Playbook (Claude Code & Antigravity)

Use these ready-made prompts when working with the **Handwriting Font & Natural PDF Generator** skill.

---

## 1. Create `.ttf` & `.otf` Handwriting Fonts from Photos

```text
Use the handwriting-font-pdf skill to build "<Name> font.ttf" and "<Name> font.otf"
from these handwriting sample photos:
- Characters & numbers: "<path/to/letters_and_numbers.jpg>"
- Punctuation & math signs: "<path/to/symbols.jpg>"

Make strokes uniform and slim (not blocky or bold), preserve all inner loops
(a, b, d, e, g, o, p, q, 0, 4, 6, 8, 9), eliminate any missing-glyph black boxes,
and render visual verification sheets for all characters and sample sentences.
```

---

## 2. Patch Individual Letters or Add Greek / Math Symbols

```text
Update "<Name> font.ttf" and "<Name> font.otf" using "<path/to/new_symbols.jpg>":
- Add all Greek letters (α–ω) and ∇ matching the stroke width and style of existing glyphs.
- Replace lowercase "w" using the sample in "<path/to/w_patch.jpg>".
- Verify "μ" works cleanly in equations.
Do not affect any previously working letters or numbers, and show a visual verification grid.
```

---

## 3. Convert an Assignment PDF into Handwritten Notes

```text
Convert "<path/to/Assignment.pdf>" into an exact handwritten PDF ("<path/to/Assignment_Handwritten.pdf>")
using "<Name> font.ttf" and "<Name> font.otf".

Match the handwriting flow, ink color, and natural page tilt shown in "<path/to/flow_reference.jpg>".
Include all equations, fractions, subscripts/superscripts, matrices, boxed tables, and block diagrams.
Keep the output file under 10 MB and visually inspect key rendered pages.
```

---

## 4. Styling, Margins, Randomness & Realism Refinements

You can combine any of these follow-up prompts:

- **Headings/Questions in Black + No Decorative Underlines:**
  ```text
  Remove all wavy/zigzag underline decorations, and render all section headings,
  cover titles, and questions in black ink while keeping answers, math, and diagrams in blue ink.
  ```
- **4-Side Natural Margins + Randomized Angles & Line Starts:**
  ```text
  Add 4-side page margins (top, bottom, left, right) with slight per-page randomness
  in angle and position. Randomize the writing angle per page and per line, and add
  natural horizontal/vertical line-start variation across every line. Keep the PDF under 10 MB.
  ```
- **Natural Boxed Grid Tables:**
  ```text
  Redraw all tables as hand-drawn boxed grids (outer box + column dividers + row lines)
  with slight pen wobble so they match real notebook handwriting.
  ```
- **Font Size Adjustment (`+1 pt`):**
  ```text
  Increase the handwriting font size by 1 point across body text, questions, headings,
  and tables while keeping margins intact and total PDF size under 10 MB.
  ```
- **Clean Cover Page:**
  ```text
  Remove extra header/footer metadata lines from Page 1 (Cover Page) so only the main
  title and subtitle remain centered.
  ```

---

## 5. Create a New Person's Handwriting Without Touching Existing Code

```text
Create the exact same font + handwritten PDF pipeline for another handwriting style inside
"<path/to/new_profile_folder>/" without modifying any files from the first handwriting setup.

- Letter & sign samples: "<path/to/person2_chars.jpg>", "<path/to/person2_greek.jpg>"
- Writing flow & angle references: "<path/to/person2_flow1.jpg>", "<path/to/person2_flow2.jpg>"
- Input PDF: "<path/to/Assignment.pdf>"

Generate "<Person2> font.ttf", "<Person2> font.otf", and "<path/to/new_profile_folder>/Assignment_Handwritten.pdf"
matching the new flow, ink color, margins, +1 pt readability, and < 10 MB size cap.
```

