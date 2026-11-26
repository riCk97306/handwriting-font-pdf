---
name: handwriting-font-pdf
description: >-
  Convert photos of handwritten letters, digits, Greek letters, and math signs into
  smooth, uniform-stroke TTF and OTF fonts, and render documents or PDFs into realistic
  handwritten assignment pages matching a reference handwriting flow photo. Use when the
  user provides handwriting sample images to build/update a font or convert a PDF/text
  into handwritten notes.
---

# Handwriting Font & Natural PDF Generator

This skill turns raw phone photos of handwritten character/symbol sheets and writing-flow
notes into production-grade `.ttf` / `.otf` fonts and natural multi-page handwritten PDFs.

## Bundled Helpers & References

- **Component & Flow Analyzer:** [analyze_sheet.py](./scripts/analyze_sheet.py)
- **Font Compilation Engine:** [font_core.py](./scripts/font_core.py)
- **Handwritten PDF Composer:** [pdf_composer.py](./scripts/pdf_composer.py)
- **Copy-Paste Prompt Playbook:** [prompts.md](./references/prompts.md)
- **Tuning & Troubleshooting Guide:** [tuning_guide.md](./references/tuning_guide.md)

---

## Workflow

### Phase 1 — Inspect Samples & Segment Glyphs
1. Run [analyze_sheet.py](./scripts/analyze_sheet.py) on every character/symbol photo:
   ```bash
   python scripts/analyze_sheet.py "<sheet_image>" --out-dir ./analysis --thresh 65 --min-area 12
   ```
   - Inspect `<stem>_annotated.png` visually before mapping any glyph!
   - If the paper has yellow highlights or bleed-through specks (common on two-sided sheets), re-run with `--thresh 75` to `85` and raise `min_area` per box when extracting.
2. Never map glyphs by blind grid assumption when a sheet contains scribbled-out mistakes, torn edges, or swapped lowercase/uppercase letters (e.g., an uppercase `I` written in the `i` slot). Verify every mapped region visually.
3. If the user provides a writing-flow reference image, measure its baseline angle and ink color:
   ```bash
   python scripts/analyze_sheet.py "<flow_image>" --flow
   ```
   - Visually inspect whether the reference uses plain paper or 4-side pen margins, what ink colors are used, and whether underline flourishes exist (omit underlines unless requested).

### Phase 2 — Build & Verify Smooth `.ttf` and `.otf` Fonts
1. Use [font_core.py](./scripts/font_core.py) (`load_ink_and_components`, `collect_region_ink`, `crop_to_harmonized_mask`, `compile_ttf_and_otf`, `render_font_previews`):
   - **Preserve inner holes:** Never flood-fill holes on closed loops (`0, 4, 6, 8, 9, a, b, d, e, g, o, p, q, A, B, D, O, P, Q, R, α, δ, θ, ρ, σ, φ, ∇, &, %, @`).
   - **Uniform slim stroke:** Use Euclidean SDF normalization (`STROKE_RADIUS_PX = 27.0`, `STROKE_MIN_PX = 22.0`, `SMOOTH_SIGMA_PX = 4.5`) so thin hairlines strengthen without collapsing tight loops and thick strokes slim evenly.
   - **Zero black boxes:** Provide a hollow rectangle `.notdef` (`make_notdef_glyph`) and ensure all printable ASCII (`32..126`), Greek letters, and math operators (`± × ÷ ≠ ≈ ≤ ≥ ∑ ∏ √ ∂ ∫ → ⇒ ⊗`) present in target text are mapped via `draw_polyline_mask` if missing from the sheet.
   - **Dual format parity:** Save `.ttf` (`TTGlyphPen`) and `.otf` (`Qu2CuPen` + `T2CharStringPen`) from the exact same outlines.
2. Generate visual specimen sheets (`render_font_previews`) and inspect both `grid` and `sentences` PNGs directly before proceeding.

### Phase 3 — Patching Existing Fonts or Switching Handwriting Profiles
- When the user asks to **update/add specific characters** (e.g., add Greek symbols, fix lowercase `w` or `μ`), update only the targeted glyph extractors in the font builder script without altering unaffected glyphs, then rebuild `.ttf` and `.otf` and verify both old and patched glyphs visually.
- When the user asks for a **second person's handwriting**, work inside a dedicated isolated folder (e.g., `./<person_name>/`) and never edit the original profile's scripts or outputs.

### Phase 4 — Compose Natural Handwritten PDFs
Use [pdf_composer.py](./scripts/pdf_composer.py) (`HandwrittenPDFComposer` primitives):
1. **Extract target PDF faithfully** (`pymupdf`) so every heading, question, bullet, equation, matrix, boxed table, and diagram block matches the source document. Keep Cover Pages clean (title & subtitle only unless requested otherwise).
2. **Match flow & realism:**
   - **Dual ink & font pairing:** Use `.otf` with light `bold_pass=True` in dark ink (`INK_BLACK`) for headings/questions/page numbers, and `.ttf` in pen blue (`INK_BLUE`) for answers, equations, matrices, and diagrams.
   - **Natural angle & line-start jitter:** Apply the measured per-page base angle + per-line angle variation + bounded horizontal random walk (`start_walk`) and subtle baseline sine wave.
   - **Margins:** When margins are enabled, draw 4 independent organic lines (top, bottom, left, right) with per-page randomized angles/offsets and keep `TEXT_X`/`MAX_LINE_W`/`START_Y`/`MAX_Y` safely inside.
   - **Boxed grid tables:** Draw outer borders plus vertical column dividers and horizontal row lines with organic pen wobble so multi-column tables read like genuine student notes.
3. **PDF Size Budget:** Export A4 pages at `220 DPI` and iterate JPEG `quality` (`78 → 72 → 66 → 60`) via `save_pdf_under_limit` until `< 10 MB`.

### Phase 5 — Final Verification Checklist
Before replying to the user:
1. Verify `.ttf` and `.otf` `getBestCmap()` coverage has zero unmapped characters used in the document.
2. Verify final PDF page count and file size (`< 10 MB`).
3. Visually inspect rendered preview PNGs (cover, contents, dense math page, table page, diagram page, final page) for clipping, overlapping margins, smudge specks, or glyph distortion.
