#!/usr/bin/env python3
"""
Core engine for building smooth, slim-stroke TTF and OTF handwriting fonts
from raw scanned/photographed ink glyphs using SDF normalization and spline tracing.
"""

import math
import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

UPM = 1000
PX_PER_FU = 2.0
STROKE_RADIUS_PX = 27.0  # 13.5 fu half-width -> clean slim uniform pen stroke
STROKE_MIN_PX = 22.0     # Reinforce ultra-thin hairlines without closing inner loops
SMOOTH_SIGMA_PX = 4.5


def load_ink_and_components(img_path: str, thresh: int = 65):
    """Isolate blue/dark pen ink (minimizes warm paper bleed-through) and return components."""
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Could not load {img_path}")
    _, g, r = cv2.split(img)
    ink = (255 - np.minimum(r, g)).astype(np.uint8)
    _, bw = cv2.threshold(ink, thresh, 255, cv2.THRESH_BINARY)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bw)
    comps = [
        (cid, int(stats[cid][0]), int(stats[cid][1]), int(stats[cid][2]), int(stats[cid][3]), int(stats[cid][4]))
        for cid in range(1, num_labels)
        if int(stats[cid][4]) >= 6
    ]
    return ink, labels, comps


def collect_region_ink(ink, labels, comps, box, custom_mask_fn=None, min_area: int = 6):
    """Extract ink crop for components whose centroids fall inside `box`=(bx1,by1,bx2,by2)."""
    bx1, by1, bx2, by2 = box
    selected = [
        c for c in comps
        if c[5] >= min_area and bx1 <= (c[1] + c[3] / 2.0) <= bx2 and by1 <= (c[2] + c[4] / 2.0) <= by2
    ]
    if not selected:
        return None

    x1 = max(0, min(c[1] for c in selected) - 4)
    y1 = max(0, min(c[2] for c in selected) - 4)
    x2 = min(ink.shape[1], max(c[1] + c[3] for c in selected) + 4)
    y2 = min(ink.shape[0], max(c[2] + c[4] for c in selected) + 4)

    lbl_crop = labels[y1:y2, x1:x2]
    sel_mask = np.zeros_like(lbl_crop, dtype=bool)
    for cid, *_ in selected:
        sel_mask |= (lbl_crop == cid)

    if custom_mask_fn is not None:
        sel_mask = custom_mask_fn(sel_mask, x1, y1)

    fringe = cv2.dilate(sel_mask.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    other_comps = (lbl_crop > 0) & (~sel_mask)
    keep_mask = fringe & (~other_comps)
    return np.where(keep_mask, ink[y1:y2, x1:x2], 0).astype(np.uint8)


def harmonize_and_smooth_mask(mask, r_target_px: float = STROKE_RADIUS_PX, r_min_px: float = STROKE_MIN_PX):
    """Normalize stroke radius via Euclidean distance transform while preserving holes."""
    d_fg = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    vals = d_fg[d_fg > 0]
    if len(vals) == 0:
        return None
    med_r = float(np.median(vals))

    if med_r < r_min_px:
        grow = min(10, int(round(r_min_px - med_r)))
        if grow > 0:
            n_before, _ = cv2.connectedComponents(255 - mask, connectivity=4)
            for g_try in range(grow, 0, -1):
                k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g_try + 1, 2 * g_try + 1))
                grown = cv2.dilate(mask, k)
                n_after, _ = cv2.connectedComponents(255 - grown, connectivity=4)
                if n_after == n_before:
                    mask = grown
                    break
            d_fg = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

    k_rad = int(round(r_target_px * 1.3))
    k_disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k_rad + 1, 2 * k_rad + 1))
    r_local = cv2.dilate(d_fg, k_disk)
    excess = np.clip(r_local - r_target_px, 0.0, None)
    peel = np.minimum(excess * 0.90, np.maximum(0.0, r_local - 14.0))
    slim_mask = ((d_fg > peel) & (mask > 0)).astype(np.uint8) * 255

    blurred = cv2.GaussianBlur(slim_mask.astype(np.float32), (0, 0), SMOOTH_SIGMA_PX)
    return (blurred >= 127.5).astype(np.uint8) * 255


def crop_to_harmonized_mask(
    crop_ink,
    target_h_fu=None,
    target_w_fu=None,
    r_target_px: float = STROKE_RADIUS_PX,
    r_min_px: float = STROKE_MIN_PX,
    fill_holes: bool = False,
    ink_thresh: int = 55,
):
    """Upscale ink crop to 2 px/fu, binarize cleanly, and harmonize stroke thickness."""
    if crop_ink is None:
        return None
    ys, xs = np.where(crop_ink > ink_thresh)
    if len(xs) == 0:
        ys, xs = np.where(crop_ink > 35)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    sub = cv2.copyMakeBorder(crop_ink[y0:y1, x0:x1], 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=0)

    h_px, w_px = max(1, y1 - y0), max(1, x1 - x0)
    scale = (target_w_fu * PX_PER_FU) / w_px if (target_w_fu is not None and target_h_fu is None) else (target_h_fu * PX_PER_FU) / h_px
    up = cv2.resize(sub.astype(np.float32), (max(8, int(round(sub.shape[1] * scale))), max(8, int(round(sub.shape[0] * scale)))), interpolation=cv2.INTER_CUBIC)

    pos = up[up > 30]
    p90 = float(np.percentile(pos, 90)) if len(pos) > 0 else 150.0
    thresh = min(75.0, max(42.0, 0.36 * p90))
    mask = cv2.copyMakeBorder((up > thresh).astype(np.uint8) * 255, 64, 64, 64, 64, cv2.BORDER_CONSTANT, value=0)

    if fill_holes:
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(mask, cnts, -1, 255, -1)

    return harmonize_and_smooth_mask(mask, r_target_px=r_target_px, r_min_px=r_min_px)


def sample_cubic(p0, p1, p2, p3, steps: int = 24):
    return [
        (
            (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0],
            (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1],
        )
        for t in np.linspace(0.0, 1.0, steps)
    ]


def sample_quad(p0, p1, p2, steps: int = 18):
    return [
        ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
         (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
        for t in np.linspace(0.0, 1.0, steps)
    ]


def draw_polyline_mask(strokes_fu, width_fu: int, height_fu: int, y_bottom_fu: int = 0, radius_px: float = STROKE_RADIUS_PX):
    """Render handwritten vector polyline strokes into a 2 px/fu smoothed mask."""
    pad_fu = 60
    mask = np.zeros((int(round((height_fu + 2 * pad_fu) * PX_PER_FU)), int(round((width_fu + 2 * pad_fu) * PX_PER_FU))), dtype=np.uint8)
    thickness = max(2, int(round(2.0 * radius_px)))
    for pts_fu in strokes_fu:
        pts_px = [[int(round((x + pad_fu) * PX_PER_FU)), int(round((height_fu + y_bottom_fu - y + pad_fu) * PX_PER_FU))] for x, y in pts_fu]
        cv2.polylines(mask, [np.array(pts_px, dtype=np.int32).reshape((-1, 1, 2))], False, 255, thickness, lineType=cv2.LINE_AA)
        for px, py in pts_px[:1] + pts_px[-1:]:
            cv2.circle(mask, (px, py), thickness // 2, 255, -1, lineType=cv2.LINE_AA)
    blurred = cv2.GaussianBlur(((mask >= 128).astype(np.uint8) * 255).astype(np.float32), (0, 0), SMOOTH_SIGMA_PX)
    return (blurred >= 127.5).astype(np.uint8) * 255


def _signed_area(pts):
    n = len(pts)
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))


def _smooth_contour_preserve_corners(pts, corner_angle_deg: float = 52.0, passes: int = 2):
    n = len(pts)
    if n < 5:
        return pts, [False] * n
    corners = [False] * n
    cos_thresh = math.cos(math.radians(180.0 - corner_angle_deg))
    for i in range(n):
        p_prev, p_curr, p_next = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        v1 = (p_prev[0] - p_curr[0], p_prev[1] - p_curr[1])
        v2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 > 4.0 and l2 > 4.0 and (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2) > cos_thresh:
            corners[i] = True
    cur = list(pts)
    for _ in range(passes):
        cur = [
            cur[i] if corners[i] else (
                0.25 * cur[(i - 1) % n][0] + 0.5 * cur[i][0] + 0.25 * cur[(i + 1) % n][0],
                0.25 * cur[(i - 1) % n][1] + 0.5 * cur[i][1] + 0.25 * cur[(i + 1) % n][1],
            )
            for i in range(n)
        ]
    return cur, corners


def mask_to_tt_glyph(smooth_mask, y_bottom_fu: int = 0, lsb: int = 48, rsb: int = 48):
    """Vectorize a binary mask into a TrueType glyph preserving TrueType winding (outer CW, holes CCW)."""
    pen = TTGlyphPen(None)
    ys, xs = np.where(smooth_mask > 0)
    if len(xs) == 0:
        return pen.glyph(), 320, 0, 0

    x0_px, x1_px, y1_px = int(xs.min()), int(xs.max()), int(ys.max())
    contours, hierarchy = cv2.findContours(smooth_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if not contours or hierarchy is None:
        return pen.glyph(), 320, 0, 0

    hier = hierarchy[0]
    contour_data = []
    for idx, cnt in enumerate(contours):
        if cv2.contourArea(cnt) < 90:
            continue
        depth, p = 0, int(hier[idx][3])
        while p != -1:
            depth += 1
            p = int(hier[p][3])
        is_hole = (depth % 2 == 1)

        approx = cv2.approxPolyDP(cnt, 2.0, True)
        if len(approx) < 3:
            continue
        pts = [((float(pt[0][0]) - x0_px) / PX_PER_FU + lsb, (y1_px - float(pt[0][1])) / PX_PER_FU + y_bottom_fu) for pt in approx]
        dedup = [pts[0]]
        for pt in pts[1:]:
            if math.hypot(pt[0] - dedup[-1][0], pt[1] - dedup[-1][1]) >= 1.5:
                dedup.append(pt)
        if len(dedup) > 2 and math.hypot(dedup[0][0] - dedup[-1][0], dedup[0][1] - dedup[-1][1]) < 1.5:
            dedup.pop()
        if len(dedup) < 3:
            continue

        sa = _signed_area(dedup)
        if (not is_hole and sa > 0) or (is_hole and sa < 0):
            dedup.reverse()

        contour_data.append(_smooth_contour_preserve_corners(dedup, corner_angle_deg=52.0, passes=2))

    if not contour_data:
        return pen.glyph(), 320, 0, 0

    for pts, corners in contour_data:
        corner_indices = [i for i, c in enumerate(corners) if c]
        if not corner_indices:
            clean = []
            for p in ((int(round(x)), int(round(y))) for x, y in pts):
                if not clean or p != clean[-1]:
                    clean.append(p)
            if len(clean) > 2 and clean[0] == clean[-1]:
                clean.pop()
            if len(clean) >= 3:
                pen.qCurveTo(*clean, None)
                pen.closePath()
        else:
            n = len(pts)
            first_c = corner_indices[0]
            pen.moveTo((int(round(pts[first_c][0])), int(round(pts[first_c][1]))))
            for k in range(len(corner_indices)):
                c_start, c_end = corner_indices[k], corner_indices[(k + 1) % len(corner_indices)]
                off_pts = []
                idx = (c_start + 1) % n
                while idx != c_end:
                    off_pts.append((int(round(pts[idx][0])), int(round(pts[idx][1]))))
                    idx = (idx + 1) % n
                end_pt = (int(round(pts[c_end][0])), int(round(pts[c_end][1])))
                if not off_pts:
                    pen.lineTo(end_pt)
                else:
                    pen.qCurveTo(*off_pts, end_pt)
            pen.closePath()

    width_fu = (x1_px - x0_px) / PX_PER_FU
    return pen.glyph(), int(round(lsb + width_fu + rsb)), lsb, int(round(lsb + width_fu))


def make_notdef_glyph():
    """Return a clean hollow rectangle .notdef glyph instead of a solid black box."""
    pen = TTGlyphPen(None)
    pen.moveTo((60, 0)); pen.lineTo((60, 700)); pen.lineTo((460, 700)); pen.lineTo((460, 0)); pen.closePath()
    pen.moveTo((100, 40)); pen.lineTo((420, 40)); pen.lineTo((420, 660)); pen.lineTo((100, 660)); pen.closePath()
    return pen.glyph(), 520


def compile_ttf_and_otf(glyph_specs, ttf_out: str, otf_out: str, family_name: str, style_name: str = "Regular"):
    """
    Build both TrueType (.ttf) and CFF OpenType (.otf) font files.

    `glyph_specs` maps unicode char (str) -> (smooth_mask, y_bottom_fu, lsb, rsb).
    """
    glyph_order = [".notdef", "space"]
    glyph_map = {}
    metrics = {".notdef": (520, 60), "space": (250, 0)}
    cmap = {0x20: "space"}

    notdef_g, _ = make_notdef_glyph()
    glyph_map[".notdef"] = notdef_g
    glyph_map["space"] = TTGlyphPen(None).glyph()

    used_names = {".notdef", "space"}
    for ch, (mask, yb, lsb, rsb) in glyph_specs.items():
        if mask is None:
            continue
        gname = f"uni{ord(ch):04X}"
        if gname in used_names:
            continue
        used_names.add(gname)
        g, adv, real_lsb, _ = mask_to_tt_glyph(mask, y_bottom_fu=yb, lsb=lsb, rsb=rsb)
        glyph_order.append(gname)
        glyph_map[gname] = g
        metrics[gname] = (adv, real_lsb)
        cmap[ord(ch)] = gname

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyph_map)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=850, descent=-250)
    fb.setupNameTable({
        "familyName": family_name,
        "styleName": style_name,
        "uniqueFontIdentifier": f"{family_name.replace(' ', '')}-{style_name}-1.0",
        "fullName": f"{family_name} {style_name}",
        "version": "Version 1.0",
        "psName": f"{family_name.replace(' ', '')}-{style_name}",
    })
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=200,
        usWinAscent=900, usWinDescent=260, sxHeight=420, sCapHeight=670,
        fsSelection=0x40, ulCodePageRange1=1,
    )
    fb.setupPost()
    fb.save(ttf_out)

    # Lossless quadratic -> cubic conversion for OTF CFF outlines
    tt = TTFont(ttf_out)
    glyf_table = tt["glyf"]
    glyph_set = tt.getGlyphSet()
    charstrings = {}
    for gname in glyph_order:
        t2_pen = T2CharStringPen(metrics[gname][0], glyphSet=glyph_set)
        q2c_pen = Qu2CuPen(t2_pen, max_err=0.5, all_cubic=False, reverse_direction=True)
        g = glyf_table[gname]
        if g.numberOfContours > 0:
            g.draw(q2c_pen, glyf_table)
        charstrings[gname] = t2_pen.getCharString()

    ps_name = f"{family_name.replace(' ', '')}-{style_name}"
    fb_otf = FontBuilder(UPM, isTTF=False)
    fb_otf.setupGlyphOrder(glyph_order)
    fb_otf.setupCharacterMap(cmap)
    fb_otf.setupCFF(
        ps_name,
        {"FullName": f"{family_name} {style_name}", "FamilyName": family_name, "Weight": style_name},
        charstrings,
        {"defaultWidthX": 0, "nominalWidthX": 0},
    )
    fb_otf.setupHorizontalMetrics(metrics)
    fb_otf.setupHorizontalHeader(ascent=850, descent=-250)
    fb_otf.setupNameTable({
        "familyName": family_name,
        "styleName": style_name,
        "uniqueFontIdentifier": f"{ps_name}-1.0",
        "fullName": f"{family_name} {style_name}",
        "version": "Version 1.0",
        "psName": ps_name,
    })
    fb_otf.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=200,
        usWinAscent=900, usWinDescent=260, sxHeight=420, sCapHeight=670,
        fsSelection=0x40, ulCodePageRange1=1,
    )
    fb_otf.setupPost()
    fb_otf.save(otf_out)
    print(f"Compiled {len(glyph_order)} glyphs ({len(cmap)} cmap entries) -> {ttf_out} & {otf_out}")


def render_font_previews(ttf_path: str, otf_path: str, out_grid_png: str, out_sentences_png: str):
    """Render visual verification sheets (all-glyph grid + mixed sentence specimen)."""
    f_ttf = ImageFont.truetype(ttf_path, 48)
    f_otf = ImageFont.truetype(otf_path, 48)
    cmap = TTFont(ttf_path).getBestCmap()
    chars = [chr(cp) for cp in sorted(cmap) if cp >= 33]

    cols, cell_w, cell_h = 14, 108, 120
    rows = max(1, (len(chars) + cols - 1) // cols)
    grid = Image.new("RGB", (cols * cell_w + 40, rows * cell_h + 40), (255, 255, 255))
    d_grid = ImageDraw.Draw(grid)
    f_lbl = ImageFont.load_default()
    for idx, ch in enumerate(chars):
        r_i, c_i = divmod(idx, cols)
        x, y = 20 + c_i * cell_w, 20 + r_i * cell_h
        d_grid.text((x + 12, y + 10), ch, font=f_ttf, fill=(18, 22, 32))
        d_grid.text((x + 8, y + 88), f"U+{ord(ch):04X}", font=f_lbl, fill=(140, 140, 150))
    grid.save(out_grid_png)

    lines = [
        ("TTF", "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        ("TTF", "abcdefghijklmnopqrstuvwxyz .,:;!?()-+=x/"),
        ("TTF", "w(n+1) = w(n) + μ e(n)x(n) | α β γ δ λ π σ ω ∇"),
        ("OTF", "Adaptive Signal Processing — Quick brown fox 42!"),
    ]
    sent = Image.new("RGB", (1750, 90 + len(lines) * 95), (255, 255, 255))
    d_sent = ImageDraw.Draw(sent)
    y = 35
    for tag, txt in lines:
        fnt = f_ttf if tag == "TTF" else f_otf
        d_sent.text((40, y), f"{tag}: {txt}", font=fnt, fill=(18, 26, 48))
        y += 90
    sent.save(out_sentences_png)

