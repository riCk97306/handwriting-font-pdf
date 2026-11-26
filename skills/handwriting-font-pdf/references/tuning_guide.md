# Tuning & Troubleshooting Guide

Reference parameters for `font_core.py`, `analyze_sheet.py`, and `pdf_composer.py`.

---

## 1. Ink Segmentation Threshold (`--thresh`)

`analyze_sheet.py` and `font_core.py` isolate pen ink via `ink = 255 - min(R, G)`.
Because warm paper shadows and yellow highlight bleed-through have high green/red values while blue/black ink suppresses R and G:

| Paper Condition | Recommended `thresh` | Recommended `min_area` |
| :--- | :--- | :--- |
| Clean white paper / bright lighting | `50 – 65` | `10 – 25` |
| Faint two-sided paper bleed-through | `75 – 85` | `60 – 120` |
| Very light ballpoint strokes | `38 – 50` | `8 – 15` |

---

## 2. Uniform Slim Stroke Tuning (`font_core.py`)

Working canvas resolution is `PX_PER_FU = 2.0` (`2 px` per font unit on a `1000 UPM` grid):

| Constant | Default | Effect |
| :--- | :--- | :--- |
| `STROKE_RADIUS_PX` | `27.0` | Target half-width in working pixels (`13.5 fu` radius -> `27 fu` diameter). Lower to `22-24` for finer pen tips; raise to `32` for marker feel. |
| `STROKE_MIN_PX` | `22.0` | Dilates ultra-thin hairlines up to `22 px` while checking 4-connected background component count (`n_after == n_before`) so inner loops (`e, a, o, g, 8, θ`) never pinch shut. |
| `SMOOTH_SIGMA_PX` | `4.5` | Gaussian anti-jag smoothing before binary contour extraction (`>= 127.5`). |

---

## 3. Font Metrics Alignment

All glyphs live in a `1000 UPM` coordinate system:
- Typo Ascender: `900`, Typo Descender: `-300`
- Cap Height: `~700 fu` (Uppercase `A–Z`, Digits `0–9`)
- x-Height: `~460–480 fu` (Small `a, c, e, m, n, o, r, s, u, v, w, x, z`)
- Ascenders: `~680–730 fu` (`b, d, f, h, k, l, t`)
- Descenders: `y_bottom_fu = -180 to -240` (`g, j, p, q, y, f, β, γ, ζ, η, μ, ξ, ρ, φ, χ, ψ`)

---

## 4. Natural Page Angle, Randomness & PDF Size Budget

- **Measuring flow angle (`analyze_sheet.py --flow`):** Reports `slope_median_deg` (CCW positive = upward-right slant).
  - Example A (steep natural slant): `page_base_ang` in `[1.6, 4.4]` deg, per-line jitter `±1.1` deg.
  - Example B (gentle slant): `page_base_ang` in `[0.5, 2.7]` deg, per-line jitter `±0.95` deg.
- **Line-start naturalness:** Use an autoregressive walk (`start_walk = clamp(start_walk * 0.65 + uniform(-14, 16), -20, 24)`) plus per-line jitter `uniform(-14, 18)` so consecutive lines drift organically instead of forming a rigid digital left ruler.
- **Font Sizing at `220 DPI` (`1819 × 2573` px A4):**
  - `1 pt ≈ 3.06 px` (`72 pt = 220 px`).
  - Default readable profile (`+1 pt` preset): `body=45`, `body_q=46`, `small=36`, `sub=30`, `sec=55`, `subsec=48`, `title=82`, `subtitle=61`, `page_num=41`.
- **PDF Size Optimization:** At `220 DPI`, trying JPEG qualities `[78, 72, 66, 60]` keeps a ~30–35 page handwritten PDF around `6.5 – 8.5 MB` (`quality=78`) while preserving sharp pen strokes.

