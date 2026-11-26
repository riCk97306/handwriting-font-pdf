#!/usr/bin/env python3
"""
Analyze handwritten character/symbol sheets and writing-flow reference images.

Usage:
  python analyze_sheet.py sheet.jpg --out-dir ./analysis --thresh 65 --min-area 12
  python analyze_sheet.py flow.png --flow
"""

import argparse
import json
import math
import os
import cv2
import numpy as np


def segment_sheet(image_path: str, out_dir: str, thresh: int = 65, min_area: int = 12):
    """Segment dark/blue pen ink into numbered connected components and save annotated PNG + JSON."""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    b, g, r = cv2.split(img)
    ink = (255 - np.minimum(r, g)).astype(np.uint8)
    _, bw = cv2.threshold(ink, thresh, 255, cv2.THRESH_BINARY)
    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(bw)

    ann = img.copy()
    items = []
    for cid in range(1, num_labels):
        x, y, w, h, area = [int(v) for v in stats[cid]]
        if area < min_area:
            continue
        cx, cy = float(centroids[cid][0]), float(centroids[cid][1])
        items.append({"id": cid, "x": x, "y": y, "w": w, "h": h, "area": area, "cx": round(cx, 1), "cy": round(cy, 1)})
        cv2.rectangle(ann, (x, y), (x + w, y + h), (0, 175, 0), 1)
        cv2.putText(ann, str(cid), (x, max(12, y - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (210, 30, 30), 1)

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    ann_path = os.path.join(out_dir, f"{stem}_annotated.png")
    json_path = os.path.join(out_dir, f"{stem}_components.json")
    cv2.imwrite(ann_path, ann)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"image": image_path, "shape": list(img.shape), "thresh": thresh, "components": items}, f, indent=2)

    print(f"Segmented {len(items)} components -> {ann_path} and {json_path}")
    return items


def analyze_flow(image_path: str, thresh: int = 70):
    """Estimate line-writing slope (degrees CCW positive) and median pen ink color from a flow sheet."""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    h_img, w_img = img.shape[:2]
    b, g, r = cv2.split(img)
    ink = (255 - np.minimum(r, g)).astype(np.uint8)
    bw = (ink > thresh).astype(np.uint8) * 255

    # Mask inner page area to ignore outer paper borders/clipboard clips
    inner = bw[int(h_img * 0.14):int(h_img * 0.90), int(w_img * 0.12):int(w_img * 0.92)]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (55, 5))
    bands = cv2.morphologyEx(inner, cv2.MORPH_CLOSE, kernel)
    cnts, _ = cv2.findContours(bands, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    slopes = []
    for cnt in cnts:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 180 or h > 95:
            continue
        pts = cnt.reshape(-1, 2).astype(np.float32)
        vx, vy, _, _ = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01)
        deg = -math.degrees(math.atan2(float(vy[0]), float(vx[0])))
        if -12.0 <= deg <= 12.0:
            slopes.append(deg)

    fg_pixels = img[bw > 0]
    med_bgr = [int(v) for v in np.median(fg_pixels, axis=0)] if len(fg_pixels) else [30, 40, 120]
    summary = {
        "image": image_path,
        "resolution": [w_img, h_img],
        "measured_lines": len(slopes),
        "slope_median_deg": round(float(np.median(slopes)), 2) if slopes else 0.0,
        "slope_range_deg": [round(float(min(slopes)), 2), round(float(max(slopes)), 2)] if slopes else [0.0, 0.0],
        "median_ink_rgb": [med_bgr[2], med_bgr[1], med_bgr[0]],
    }
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description="Analyze handwriting sheets or writing-flow reference images.")
    parser.add_argument("image", help="Path to sheet or flow reference image")
    parser.add_argument("--out-dir", default="./analysis", help="Output directory for component annotations")
    parser.add_argument("--thresh", type=int, default=65, help="Ink threshold (raise to 75-85 if paper has bleed-through)")
    parser.add_argument("--min-area", type=int, default=12, help="Minimum connected-component pixel area")
    parser.add_argument("--flow", action="store_true", help="Measure writing angle & ink color instead of character boxes")
    args = parser.parse_args()

    if args.flow:
        analyze_flow(args.image, thresh=args.thresh)
    else:
        segment_sheet(args.image, args.out_dir, thresh=args.thresh, min_area=args.min_area)


if __name__ == "__main__":
    main()

