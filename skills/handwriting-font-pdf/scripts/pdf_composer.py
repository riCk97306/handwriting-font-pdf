#!/usr/bin/env python3
"""
Compose realistic handwritten assignment PDFs from structured content elements using
paired TTF (body/math) and OTF (headings/questions/numbers) handwriting fonts.
"""

import io
import math
import os
import random
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

PAGE_W = 1819  # A4 @ 220 DPI
PAGE_H = 2573


class HandwritingFonts:
    """Paired TTF/OTF font bundle scaled cleanly at 220 DPI."""

    def __init__(self, ttf_path: str, otf_path: str, scale: float = 1.0):
        s = lambda px: max(12, int(round(px * scale)))
        self.body = ImageFont.truetype(ttf_path, s(45))
        self.body_q = ImageFont.truetype(otf_path, s(46))
        self.sub = ImageFont.truetype(ttf_path, s(30))
        self.small = ImageFont.truetype(ttf_path, s(36))
        self.sec = ImageFont.truetype(otf_path, s(55))
        self.subsec = ImageFont.truetype(otf_path, s(48))
        self.title = ImageFont.truetype(otf_path, s(82))
        self.subtitle = ImageFont.truetype(otf_path, s(61))
        self.page_num = ImageFont.truetype(otf_path, s(41))


def draw_organic_line(draw, p1, p2, color, width=2, wobble=1.7, rng=None):
    rng = rng or random.Random(42)
    x1, y1 = p1
    x2, y2 = p2
    dist = math.hypot(x2 - x1, y2 - y1)
    steps = max(4, int(dist / 28))
    dx, dy = (x2 - x1) / max(1e-6, dist), (y2 - y1) / max(1e-6, dist)
    nx, ny = -dy, dx
    phase = rng.uniform(0, 2 * math.pi)
    pts = [
        (
            x1 + (x2 - x1) * (i / steps) + nx * (math.sin((i / steps) * math.pi) * wobble * math.sin((i / steps) * 6.5 + phase) + rng.uniform(-0.5, 0.5)),
            y1 + (y2 - y1) * (i / steps) + ny * (math.sin((i / steps) * math.pi) * wobble * math.sin((i / steps) * 6.5 + phase) + rng.uniform(-0.5, 0.5)),
        )
        for i in range(steps + 1)
    ]
    draw.line(pts, fill=color, width=width, joint="curve")


def draw_organic_rect(draw, box, color, width=2, rng=None):
    x1, y1, x2, y2 = box
    draw_organic_line(draw, (x1, y1), (x2, y1), color, width, 1.3, rng)
    draw_organic_line(draw, (x2, y1), (x2, y2), color, width, 1.3, rng)
    draw_organic_line(draw, (x2, y2), (x1, y2), color, width, 1.3, rng)
    draw_organic_line(draw, (x1, y2), (x1, y1), color, width, 1.3, rng)


def _read_braced(s, idx):
    depth, start, i = 0, idx + 1, idx
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    return s[start:], len(s)


def parse_math_nodes(s):
    """Parse lightweight LaTeX-like markup (\\frac, \\boxed, \\hat, \\tilde, \\sum, _, ^)."""
    nodes, buf, i = [], [], 0
    flush = lambda: (nodes.append(("text", "".join(buf))), buf.clear()) if buf else None
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            if s.startswith("\\frac{", i):
                flush(); n_s, j = _read_braced(s, i + 5)
                d_s, j = _read_braced(s, j) if (j < len(s) and s[j] == "{") else ("", j)
                nodes.append(("frac", parse_math_nodes(n_s), parse_math_nodes(d_s))); i = j; continue
            if s.startswith("\\boxed{", i):
                flush(); inner, j = _read_braced(s, i + 6)
                nodes.append(("boxed", parse_math_nodes(inner))); i = j; continue
            if s.startswith("\\hat{", i) or s.startswith("\\tilde{", i):
                flush(); off = 4 if s.startswith("\\hat{", i) else 6
                inner, j = _read_braced(s, i + off)
                nodes.append(("accent", "^" if off == 4 else "~", parse_math_nodes(inner))); i = j; continue
            if s.startswith("\\sum", i) or s.startswith("\\prod", i):
                flush(); op = "∑" if s.startswith("\\sum", i) else "∏"
                j = i + (4 if op == "∑" else 5)
                sub_n, sup_n = None, None
                while j < len(s) and s[j] in ("_", "^"):
                    kind = s[j]; j += 1
                    if j < len(s) and s[j] == "{":
                        inner, j = _read_braced(s, j); parsed = parse_math_nodes(inner)
                    elif j < len(s):
                        parsed, j = [("text", s[j])], j + 1
                    else:
                        parsed = []
                    if kind == "_": sub_n = parsed
                    else: sup_n = parsed
                nodes.append(("bigop", op, sub_n, sup_n)); i = j; continue
            buf.append(ch); i += 1
        elif ch in ("_", "^"):
            flush(); kind = "sub" if ch == "_" else "sup"; j = i + 1
            if j < len(s) and s[j] == "{":
                inner, j = _read_braced(s, j); parsed = parse_math_nodes(inner)
            elif j < len(s):
                parsed, j = [("text", s[j])], j + 1
            else:
                parsed = []
            nodes.append((kind, parsed)); i = j
        else:
            buf.append(ch); i += 1
    flush()
    return nodes


def measure_nodes(nodes, f_main, f_sub):
    w, asc, desc = 0, int(f_main.size * 0.85), int(f_main.size * 0.25)
    mt = lambda f, t: int(math.ceil(f.getlength(t))) if t else 0
    for nd in nodes:
        k = nd[0]
        if k == "text": w += mt(f_main, nd[1])
        elif k == "sub": sw, _, sd = measure_nodes(nd[1], f_sub, f_sub); w += sw + 2; desc = max(desc, int(f_main.size * 0.22) + sd)
        elif k == "sup": sw, sa, _ = measure_nodes(nd[1], f_sub, f_sub); w += sw + 2; asc = max(asc, int(f_main.size * 0.42) + sa)
        elif k == "accent": iw, ia, id_ = measure_nodes(nd[2], f_main, f_sub); w += max(iw, 16); asc = max(asc, ia + 14); desc = max(desc, id_)
        elif k == "frac":
            nw, na, n_d = measure_nodes(nd[1], f_sub, f_sub); dw, da, dd = measure_nodes(nd[2], f_sub, f_sub)
            w += max(nw, dw) + 18; asc = max(asc, int(f_main.size * 0.35) + na + n_d + 8); desc = max(desc, da + dd + 3)
        elif k == "boxed": iw, ia, id_ = measure_nodes(nd[1], f_main, f_sub); w += iw + 24; asc = max(asc, ia + 10); desc = max(desc, id_ + 10)
        elif k == "bigop":
            _, op, sn, pn = nd
            w += max(mt(f_main, op) + 6, measure_nodes(sn, f_sub, f_sub)[0] if sn else 0, measure_nodes(pn, f_sub, f_sub)[0] if pn else 0) + 6
            if pn: asc = max(asc, int(f_main.size * 0.95) + 18)
            if sn: desc = max(desc, int(f_main.size * 0.45) + 16)
    return w, asc, desc


def draw_text_natural(draw, x, baseline_y, txt, font, color, rng, wave_phase=0.0, bold_pass=False):
    cx = float(x)
    ascent, _ = font.getmetrics()
    for ch in txt:
        if ch == " ":
            cx += font.getlength(" "); continue
        jy = rng.uniform(-1.3, 1.3) + 1.8 * math.sin(cx * 0.013 + wave_phase)
        draw.text((cx, baseline_y - ascent + jy), ch, font=font, fill=color)
        draw.text((cx + 0.45, baseline_y - ascent + jy + 0.25), ch, font=font, fill=color)
        if bold_pass:
            draw.text((cx + 0.95, baseline_y - ascent + jy + 0.5), ch, font=font, fill=color)
        cx += font.getlength(ch) + rng.uniform(-0.3, 0.4)
    return cx


def draw_nodes(draw, x, baseline_y, nodes, f_main, f_sub, color, rng, wave_phase=0.0, bold_pass=False):
    cx = float(x)
    for nd in nodes:
        k = nd[0]
        if k == "text": cx = draw_text_natural(draw, cx, baseline_y, nd[1], f_main, color, rng, wave_phase, bold_pass)
        elif k == "sub": cx = draw_nodes(draw, cx, baseline_y + int(f_main.size * 0.24), nd[1], f_sub, f_sub, color, rng, wave_phase, bold_pass) + 2
        elif k == "sup": cx = draw_nodes(draw, cx, baseline_y - int(f_main.size * 0.38), nd[1], f_sub, f_sub, color, rng, wave_phase, bold_pass) + 2
        elif k == "accent":
            acc, inner = nd[1], nd[2]; iw, _, _ = measure_nodes(inner, f_main, f_sub)
            draw_nodes(draw, cx, baseline_y, inner, f_main, f_sub, color, rng, wave_phase, bold_pass)
            ax, ay = cx + iw * 0.5, baseline_y - int(f_main.size * 0.78)
            pts = [(ax - 7, ay + 5), (ax, ay - 2), (ax + 7, ay + 5)] if acc == "^" else [(ax - 8, ay + 2), (ax - 3, ay - 2), (ax + 3, ay + 3), (ax + 8, ay - 1)]
            draw.line(pts, fill=color, width=2); cx += max(iw, 16)
        elif k == "frac":
            nn, dn = nd[1], nd[2]; nw, _, n_d = measure_nodes(nn, f_sub, f_sub); dw, da, _ = measure_nodes(dn, f_sub, f_sub)
            fw = max(nw, dw) + 15; bar_y = baseline_y - int(f_main.size * 0.28)
            draw_nodes(draw, cx + (fw - nw) * 0.5, bar_y - n_d - 5, nn, f_sub, f_sub, color, rng, wave_phase, bold_pass)
            draw_organic_line(draw, (cx + 2, bar_y), (cx + fw - 2, bar_y), color, 2, 1.0, rng)
            draw_nodes(draw, cx + (fw - dw) * 0.5, bar_y + da + 5, dn, f_sub, f_sub, color, rng, wave_phase, bold_pass)
            cx += fw + 4
        elif k == "boxed":
            iw, ia, id_ = measure_nodes(nd[1], f_main, f_sub); pad_x = 10
            draw_nodes(draw, cx + pad_x, baseline_y, nd[1], f_main, f_sub, color, rng, wave_phase, bold_pass)
            draw_organic_rect(draw, (cx + 2, baseline_y - ia + 2, cx + iw + 2 * pad_x - 2, baseline_y + id_), color, 2, rng)
            cx += iw + 2 * pad_x + 4
        elif k == "bigop":
            _, op, sn, pn = nd; op_w = int(math.ceil(f_main.getlength(op)))
            sw = measure_nodes(sn, f_sub, f_sub)[0] if sn else 0; pw = measure_nodes(pn, f_sub, f_sub)[0] if pn else 0
            bw = max(op_w, sw, pw) + 9
            draw_text_natural(draw, cx + (bw - op_w) * 0.5, baseline_y + 3, op, f_main, color, rng, wave_phase, bold_pass)
            if pn: draw_nodes(draw, cx + (bw - pw) * 0.5, baseline_y - int(f_main.size * 0.72), pn, f_sub, f_sub, color, rng, wave_phase, bold_pass)
            if sn: draw_nodes(draw, cx + (bw - sw) * 0.5, baseline_y + int(f_main.size * 0.45), sn, f_sub, f_sub, color, rng, wave_phase, bold_pass)
            cx += bw + 4
    return cx


def create_paper_page(page_num_label, fonts, rng, with_margins=True, ink_margin=(26, 46, 138), ink_black=(18, 20, 25)):
    """Generate soft white paper with optional randomized 4-side hand-drawn margins."""
    yy, xx = np.mgrid[0:PAGE_H, 0:PAGE_W]
    vignette = 2.8 * (((xx - PAGE_W * 0.5) / PAGE_W) ** 2 + ((yy - PAGE_H * 0.48) / PAGE_H) ** 2)
    rgb = np.stack([
        np.clip(253.0 - vignette, 246, 255).astype(np.uint8),
        np.clip(252.8 - vignette, 246, 255).astype(np.uint8),
        np.clip(251.5 - vignette * 0.8, 244, 255).astype(np.uint8),
    ], axis=2)
    page = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    draw = ImageDraw.Draw(page)
    if with_margins:
        lx_t, lx_b = 150 + rng.uniform(-18, 18), 150 + rng.uniform(-24, 24)
        rx_t, rx_b = 1735 + rng.uniform(-18, 18), 1735 + rng.uniform(-24, 24)
        ty_l, ty_r = 200 + rng.uniform(-22, 22), 172 + rng.uniform(-35, 28)
        by_l, by_r = 2430 + rng.uniform(-22, 22), 2410 + rng.uniform(-30, 30)
        draw_organic_line(draw, (lx_t, 55), (lx_b, PAGE_H - 48), ink_margin, 2, 2.6, rng)
        draw_organic_line(draw, (rx_t, 55), (rx_b, PAGE_H - 48), ink_margin, 2, 2.6, rng)
        draw_organic_line(draw, (55, ty_l), (PAGE_W - 48, ty_r), ink_margin, 2, 2.4, rng)
        draw_organic_line(draw, (55, by_l), (PAGE_W - 48, by_r), ink_margin, 2, 2.4, rng)
    if page_num_label is not None:
        nd = parse_math_nodes(str(page_num_label))
        w, asc, desc = measure_nodes(nd, fonts.page_num, fonts.sub)
        st = Image.new("RGBA", (max(48, w + 36), asc + desc + 34), (0, 0, 0, 0))
        draw_nodes(ImageDraw.Draw(st), 14, 16 + asc, nd, fonts.page_num, fonts.sub, ink_black, rng, rng.uniform(0, 6.28), bold_pass=True)
        paste_tilted(page, st, 1570 + rng.uniform(-25, 25), 98 + rng.uniform(-12, 12), rng.uniform(0.3, 3.5))
    return page


def paste_tilted(page, strip, x_anchor, y_anchor, angle_deg):
    """Rotate strip gently CCW (`angle_deg` > 0 = upward-right slope) and alpha-composite onto page."""
    w, _ = strip.size
    rot = strip.rotate(angle_deg, resample=Image.BICUBIC, expand=True) if abs(angle_deg) > 0.01 else strip
    arr = np.array(rot)
    arr[:, :, 3] = np.clip(arr[:, :, 3].astype(np.float32) * 1.32, 0, 255).astype(np.uint8)
    rot_sharp = Image.fromarray(arr, mode="RGBA")
    rw, rh = rot_sharp.size
    rad = math.radians(angle_deg)
    ox = -w / 2.0
    rx = ox * math.cos(rad) + rw / 2.0
    ry = -ox * math.sin(rad) + rh / 2.0
    page.alpha_composite(rot_sharp, (int(round(x_anchor - rx)), int(round(y_anchor - ry))))


def draw_arrow(draw, p1, p2, color, width=2, head_len=12, rng=None):
    """Draw an organic line terminating with a pen arrowhead at `p2`."""
    draw_organic_line(draw, p1, p2, color, width, 1.1, rng)
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    for delta in (150, -150):
        a = ang + math.radians(delta)
        draw.line([(p2[0] + head_len * math.cos(a), p2[1] + head_len * math.sin(a)), p2], fill=color, width=width)


def tokenize_rich_text(s: str):
    """Split text on top-level spaces without breaking inside `{...}` LaTeX groups."""
    tokens, cur, depth = [], [], 0
    for ch in s:
        if ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == " " and depth == 0:
            if cur:
                tokens.append("".join(cur))
                cur.clear()
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


def wrap_rich_text(s: str, max_w: int, f_main, f_sub):
    """Word-wrap rich math/text strings to stay within `max_w` pixels."""
    lines, cur, cur_w = [], [], 0
    sp_w = int(math.ceil(f_main.getlength(" ")))
    for tok in tokenize_rich_text(s):
        tw, _, _ = measure_nodes(parse_math_nodes(tok), f_main, f_sub)
        if cur and cur_w + sp_w + tw > max_w:
            lines.append(" ".join(cur))
            cur, cur_w = [tok], tw
        else:
            cur_w = tw if not cur else cur_w + sp_w + tw
            cur.append(tok)
    if cur:
        lines.append(" ".join(cur))
    return lines or [""]


def render_line_strip(text: str, f_main, f_sub, color, rng, bold_pass: bool = False, max_w: int = 1390):
    """Render one rich math/text line onto a transparent RGBA strip."""
    nodes = parse_math_nodes(text)
    w, asc, desc = measure_nodes(nodes, f_main, f_sub)
    pad_l, pad_r, pad_t, pad_b = 14, 28, 16, 18
    strip = Image.new("RGBA", (max(48, min(max_w + 90, w + pad_l + pad_r)), asc + desc + pad_t + pad_b), (0, 0, 0, 0))
    base_y = pad_t + asc
    draw_nodes(ImageDraw.Draw(strip), pad_l, base_y, nodes, f_main, f_sub, color, rng, rng.uniform(0, 6.28), bold_pass=bold_pass)
    return strip, pad_l, base_y


def render_table_strip(headers, rows, fonts, rng, ink_black=(18, 20, 25), ink_blue=(18, 42, 148), ink_grid=(36, 42, 92), max_table_w: int = 1280):
    """Render a natural hand-drawn boxed grid table (outer borders, column dividers, row lines)."""
    f, fs = fonts.small, fonts.sub
    ncols = len(headers)
    col_widths = [0] * ncols
    for c in range(ncols):
        col_widths[c] = measure_nodes(parse_math_nodes(headers[c]), f, fs)[0] + 46
        for row in rows:
            col_widths[c] = max(col_widths[c], measure_nodes(parse_math_nodes(row[c]), f, fs)[0] + 46)
    if sum(col_widths) > max_table_w:
        sc = max_table_w / sum(col_widths)
        col_widths = [int(w * sc) for w in col_widths]

    line_step = max(36, int(round(f.size * 1.25)))
    wrapped_rows, row_heights = [], []
    for row in rows:
        w_cells, max_lines = [], 1
        for c, cell in enumerate(row):
            lines = wrap_rich_text(cell, max(120, col_widths[c] - 26), f, fs)
            w_cells.append(lines)
            max_lines = max(max_lines, len(lines))
        wrapped_rows.append(w_cells)
        row_heights.append(max(int(round(f.size * 1.55)), max_lines * line_step + 16))

    hdr_h = max(52, int(round(f.size * 1.62)))
    total_w, total_h = sum(col_widths) + 32, hdr_h + sum(row_heights) + 32
    img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x0, y0 = 16, 16
    x_end, y_end = x0 + sum(col_widths), y0 + hdr_h + sum(row_heights)
    draw_organic_line(draw, (x0 - 4, y0), (x_end + 4, y0), ink_black, 2, 1.4, rng)
    draw_organic_line(draw, (x0 - 3, y_end), (x_end + 3, y_end), ink_black, 2, 1.4, rng)
    draw_organic_line(draw, (x0, y0 - 3), (x0, y_end + 3), ink_black, 2, 1.3, rng)
    draw_organic_line(draw, (x_end, y0 - 3), (x_end, y_end + 3), ink_black, 2, 1.3, rng)

    cx = x0
    for c in range(ncols - 1):
        cx += col_widths[c]
        draw_organic_line(draw, (cx, y0), (cx, y_end), ink_black, 2, 1.3, rng)

    cx = x0
    for c, htxt in enumerate(headers):
        draw_nodes(draw, cx + 14 + rng.uniform(-3, 5), y0 + int(hdr_h * 0.68) + rng.uniform(-2, 2), parse_math_nodes(htxt), f, fs, ink_black, rng, bold_pass=True)
        cx += col_widths[c]
    y_cur = y0 + hdr_h
    draw_organic_line(draw, (x0, y_cur), (x_end, y_cur), ink_black, 2, 1.4, rng)

    for r_i, w_cells in enumerate(wrapped_rows):
        rh, cx = row_heights[r_i], x0
        for c, lines in enumerate(w_cells):
            for l_i, ln in enumerate(lines):
                draw_nodes(draw, cx + 14 + rng.uniform(-3, 6), y_cur + int(f.size * 1.0) + l_i * line_step + rng.uniform(-2, 2), parse_math_nodes(ln), f, fs, ink_blue, rng)
            cx += col_widths[c]
        y_cur += rh
        if r_i < len(wrapped_rows) - 1:
            draw_organic_line(draw, (x0, y_cur), (x_end, y_cur), ink_grid, 2, 1.3, rng)
    return img, 0, total_h // 2


def save_pdf_under_limit(pil_pages, out_path: str, max_mb: float = 9.6):
    """Export PIL page images to A4 PDF while staying cleanly below `max_mb`."""
    a4_w, a4_h = 595.28, 841.89
    for quality in (78, 72, 66, 60):
        doc = pymupdf.open()
        for pg in pil_pages:
            buf = io.BytesIO()
            pg.save(buf, format="JPEG", quality=quality, optimize=True)
            doc.new_page(width=a4_w, height=a4_h).insert_image(pymupdf.Rect(0, 0, a4_w, a4_h), stream=buf.getvalue())
        doc.save(out_path, deflate=True)
        doc.close()
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
        if size_mb <= max_mb:
            return size_mb, quality
    return os.path.getsize(out_path) / (1024 * 1024), 60


def compose_handwritten_pdf(
    ttf_path: str,
    otf_path: str,
    elements,
    contents_items,
    cover: dict,
    out_pdf_path: str,
    *,
    font_scale: float = 1.0,
    with_margins: bool = True,
    text_x: int = 215,
    max_line_w: int = 1390,
    start_y: int = 325,
    max_y: int = 2340,
    base_angle_range=(1.6, 4.4),
    line_jitter_range=(-1.1, 1.1),
    ink_black=(18, 20, 25),
    ink_blue=(18, 42, 148),
    ink_grid=(36, 42, 92),
    ink_margin=(26, 46, 138),
    max_mb: float = 9.6,
    seed: int = 20261126,
    custom_figure_fn=None,
    custom_diagram_fn=None,
):
    """Render full structured document (`elements`, `contents_items`, `cover`) into a handwritten A4 PDF."""
    rng = random.Random(seed)
    fonts = HandwritingFonts(ttf_path, otf_path, scale=font_scale)

    blocks = []
    for item in elements:
        etype = item[0]
        if etype == "sec":
            _, sec_id, text = item
            st, _, _ = render_line_strip(text, fonts.sec, fonts.sub, ink_black, rng, bold_pass=True, max_w=max_line_w)
            blocks.append({"kind": "sec", "sec_id": sec_id, "strip": st, "x": text_x, "h": st.height + 18, "space_before": 22})
        elif etype == "subsec":
            _, text = item
            st, _, _ = render_line_strip(text, fonts.subsec, fonts.sub, ink_black, rng, bold_pass=True, max_w=max_line_w)
            blocks.append({"kind": "subsec", "strip": st, "x": text_x + 10, "h": st.height + 12, "space_before": 14})
        elif etype == "q":
            _, text = item
            lines = wrap_rich_text(text, max_line_w, fonts.body_q, fonts.sub)
            q_strips = [render_line_strip(ln, fonts.body_q, fonts.sub, ink_black, rng, bold_pass=True, max_w=max_line_w)[0] for ln in lines]
            blocks.append({"kind": "q", "strips": q_strips, "x": text_x, "h": sum(s.height + 4 for s in q_strips) + 5, "space_before": 15})
        elif etype == "p":
            _, text = item
            for li, ln in enumerate(wrap_rich_text(text, max_line_w - 45, fonts.body, fonts.sub)):
                st, _, _ = render_line_strip(ln, fonts.body, fonts.sub, ink_blue, rng, max_w=max_line_w)
                blocks.append({"kind": "line", "strip": st, "x": text_x + (42 if li == 0 else 10), "h": st.height + 3, "space_before": 2 if li == 0 else 0})
        elif etype == "b":
            _, text = item
            for li, ln in enumerate(wrap_rich_text(text, max_line_w - 95, fonts.body, fonts.sub)):
                st, _, _ = render_line_strip(("• " if li == 0 else "") + ln, fonts.body, fonts.sub, ink_blue, rng, max_w=max_line_w)
                blocks.append({"kind": "line", "strip": st, "x": text_x + (52 if li == 0 else 84), "h": st.height + 3, "space_before": 2 if li == 0 else 0})
        elif etype == "n":
            _, num_lbl, text = item
            for li, ln in enumerate(wrap_rich_text(text, max_line_w - 105, fonts.body, fonts.sub)):
                st, _, _ = render_line_strip((f"{num_lbl} " if li == 0 else "") + ln, fonts.body, fonts.sub, ink_blue, rng, max_w=max_line_w)
                blocks.append({"kind": "line", "strip": st, "x": text_x + (46 if li == 0 else 92), "h": st.height + 3, "space_before": 2 if li == 0 else 0})
        elif etype == "eq":
            _, text = item
            st, _, _ = render_line_strip(text, fonts.body, fonts.sub, ink_blue, rng, max_w=max_line_w)
            blocks.append({"kind": "eq", "strip": st, "x": max(text_x + 20, text_x + (max_line_w - st.width) // 2), "h": st.height + 12, "space_before": 6})
        elif etype == "table":
            _, headers, rows = item
            st, _, _ = render_table_strip(headers, rows, fonts, rng, ink_black, ink_blue, ink_grid)
            blocks.append({"kind": "table", "strip": st, "x": max(text_x + 30, text_x + (max_line_w - st.width) // 2), "h": st.height + 64, "space_before": 14})
        elif etype.startswith("mat_") and custom_figure_fn is not None:
            st, _, _ = custom_figure_fn(etype, fonts, ink_blue, rng)
            blocks.append({"kind": "fig", "strip": st, "x": text_x + 35, "h": st.height + 10, "space_before": 6})
        elif etype == "diag" and custom_diagram_fn is not None:
            st, _, _ = custom_diagram_fn(item[1], fonts, ink_blue, rng)
            blocks.append({"kind": "fig", "strip": st, "x": text_x + 45, "h": st.height + 14, "space_before": 8})

    pages_blocks, cur_page, cur_y, sec_pages = [], [], start_y, {}
    for i, blk in enumerate(blocks):
        needed = blk["h"] + (blk["space_before"] if cur_page else 0)
        lookahead = (blocks[i + 1]["h"] + blocks[i + 1]["space_before"]) if (blk["kind"] in ("sec", "subsec", "q") and i + 1 < len(blocks)) else 0
        if cur_page and (cur_y + needed + lookahead > max_y):
            pages_blocks.append(cur_page)
            cur_page, cur_y = [], start_y
            needed = blk["h"]
        y_pos = cur_y + (blk["space_before"] if cur_page else 0)
        cur_page.append((blk, y_pos))
        if blk["kind"] == "sec":
            sec_pages[blk["sec_id"]] = len(pages_blocks) + 2
        cur_y = y_pos + blk["h"]
    if cur_page:
        pages_blocks.append(cur_page)

    # Cover page
    cov_page = create_paper_page(None, fonts, rng, with_margins=with_margins, ink_margin=ink_margin, ink_black=ink_black)
    for key, font, y_mid in (("title", fonts.title, 1080), ("subtitle", fonts.subtitle, 1255)):
        if cover.get(key):
            st, _, _ = render_line_strip(cover[key], font, fonts.sub, ink_black, rng, bold_pass=True, max_w=max_line_w + 60)
            paste_tilted(cov_page, st, (PAGE_W - st.width) * 0.5 + rng.uniform(-15, 25), y_mid + st.height * 0.15, rng.uniform(*base_angle_range))

    # Contents page
    toc_page = create_paper_page("1", fonts, rng, with_margins=with_margins, ink_margin=ink_margin, ink_black=ink_black)
    toc_ang = rng.uniform(*base_angle_range)
    st_hdr, _, _ = render_line_strip("Contents", fonts.sec, fonts.sub, ink_black, rng, bold_pass=True, max_w=max_line_w)
    paste_tilted(toc_page, st_hdr, text_x + rng.uniform(-15, 22), start_y + 38, toc_ang + rng.uniform(-0.6, 0.6))
    y_toc = start_y + 135
    for num, title, sec_id in contents_items:
        ang = toc_ang + rng.uniform(-0.85, 0.85)
        st_l, _, _ = render_line_strip(f"{num}   {title}", fonts.body_q, fonts.sub, ink_black, rng, bold_pass=True, max_w=max_line_w)
        st_p, _, _ = render_line_strip(str(sec_pages.get(sec_id, "")), fonts.body, fonts.sub, ink_blue, rng, max_w=max_line_w)
        jx, jy = rng.uniform(-18, 26), rng.uniform(-5, 5)
        paste_tilted(toc_page, st_l, text_x + 12 + jx, y_toc + 26 + jy, ang)
        dx = max_line_w - 55 + rng.uniform(-12, 12)
        paste_tilted(toc_page, st_p, text_x + dx + jx, y_toc + 26 + jy - dx * math.tan(math.radians(ang)), ang)
        y_toc += 88

    pdf_pages = [cov_page.convert("RGB"), toc_page.convert("RGB")]
    for p_idx, p_blks in enumerate(pages_blocks):
        page = create_paper_page(str(p_idx + 2), fonts, rng, with_margins=with_margins, ink_margin=ink_margin, ink_black=ink_black)
        page_base = rng.uniform(*base_angle_range)
        page_drift = rng.uniform(-0.6, 0.6)
        start_walk = rng.uniform(-14.0, 14.0)
        for blk, y_pos in p_blks:
            ang = max(-0.8, min(6.2, page_base + page_drift * (y_pos / PAGE_H) + rng.uniform(*line_jitter_range)))
            start_walk = max(-20.0, min(24.0, start_walk * 0.65 + rng.uniform(-14.0, 16.0)))
            jx, jy = start_walk + rng.uniform(-14.0, 18.0), rng.uniform(-4.5, 4.5)
            if blk["kind"] == "q":
                cy = y_pos + jy
                for st in blk["strips"]:
                    paste_tilted(page, st, blk["x"] + start_walk + rng.uniform(-16.0, 20.0), cy + st.height * 0.5, ang + rng.uniform(-0.55, 0.55))
                    cy += st.height + 4 + rng.uniform(-1.5, 2.5)
            elif blk["kind"] == "table":
                paste_tilted(page, blk["strip"], blk["x"] + rng.uniform(-10, 14), y_pos + blk["strip"].height * 0.5 + 16 + jy, page_base * 0.5 + rng.uniform(-0.6, 0.6))
            else:
                paste_tilted(page, blk["strip"], blk["x"] + jx, y_pos + blk["strip"].height * 0.5 + jy, ang)
        pdf_pages.append(page.convert("RGB"))

    size_mb, used_q = save_pdf_under_limit(pdf_pages, out_pdf_path, max_mb=max_mb)
    return {"pages": len(pdf_pages), "size_mb": round(size_mb, 2), "quality": used_q}

