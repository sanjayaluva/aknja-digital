#!/usr/bin/env python
"""Structural verification for visual-baseline regeneration.

When `pytest tests/e2e/test_visual.py` reports a diff above the 0.2% tolerance,
regenerating the baseline is only legitimate after proving the change is NOT a
layout regression. This tool compares the old and new PNG and reports:

  1. canvas sizes (identical => no layout change)
  2. full-image pixel-diff ratio (channel delta > 16 counts as changed)
  3. edge-map diff ratio (layout structure: borders, table lines)
  4. changed-row band analysis — text drift clusters in bands of ~text-line
     height (8-15px); layout changes produce bands > 100px or size changes

Verdict rules (printed, exit 0 = drift-only, 1 = suspicious, 2 = usage error):
  drift-only    — same size, bands all text-height
  suspicious    — size changed, or wide/tall bands present, or edge diff > 3%

Usage:
  python infra/baseline_verify.py --old old.png --new new.png \
      [--region 307,1616,1195,3062]

The --region crops both images to the reported diff bbox before analysis
(optional; full-image analysis is the default).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

TEXT_BAND_MAX = 15  # px — tallest plausible text-line band
EDGE_SUSPICIOUS = 0.03  # edge-map diff ratio above this = structure changed


def changed_ratio(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b).convert("L")
    hist = diff.histogram()
    changed = sum(hist[17:])
    return changed / (a.size[0] * a.size[1])


def main() -> int:
    parser = argparse.ArgumentParser(description="visual baseline drift verification")
    parser.add_argument("--old", required=True, help="baseline PNG before regeneration")
    parser.add_argument("--new", required=True, help="capture PNG after regeneration")
    parser.add_argument("--region", default=None, help="x1,y1,x2,y2 crop (diff bbox)")
    args = parser.parse_args()

    old_path, new_path = Path(args.old), Path(args.new)
    for p in (old_path, new_path):
        if not p.is_file():
            print(f"ERROR: not found: {p}", file=sys.stderr)
            return 2

    old = Image.open(old_path).convert("RGB")
    new = Image.open(new_path).convert("RGB")
    if args.region:
        region = tuple(int(v) for v in args.region.split(","))
        old, new = old.crop(region), new.crop(region)

    size_ok = old.size == new.size
    pixel = changed_ratio(old, new)
    edge = changed_ratio(
        old.convert("L").filter(ImageFilter.FIND_EDGES),
        new.convert("L").filter(ImageFilter.FIND_EDGES),
    )

    # row-wise changed-pixel profile -> contiguous bands
    diff = ImageChops.difference(old, new).convert("L")
    px = diff.load()
    rows = [
        sum(1 for x in range(0, old.size[0], 4) if px[x, y] > 16) / (old.size[0] // 4)
        for y in range(old.size[1])
    ]
    active = [i for i, r in enumerate(rows) if r > 0.01]
    bands: list[list[int]] = []
    for i in active:
        if bands and i - bands[-1][1] <= 3:
            bands[-1][1] = i
        else:
            bands.append([i, i])
    heights = [b[1] - b[0] + 1 for b in bands]

    print(f"canvas:      {old.size} vs {new.size} -> {'identical' if size_ok else 'CHANGED'}")
    print(f"pixel diff:  {pixel:.4%}")
    print(f"edge diff:   {edge:.4%} (structure; suspicious above {EDGE_SUSPICIOUS:.0%})")
    if bands:
        print(f"bands:       {len(bands)} changed row-bands "
              f"(y={bands[0][0]}..{bands[-1][1]}), heights min={min(heights)} max={max(heights)}")
    else:
        print("bands:       none (pixel-identical)")

    text_only = bool(heights) and max(heights) <= TEXT_BAND_MAX
    verdict = "drift-only (text/glyph rendering; regeneration legitimate)" if (
        size_ok and text_only and edge <= EDGE_SUSPICIOUS
    ) else "suspicious (review manually BEFORE regenerating)"
    print(f"verdict:     {verdict}")
    return 0 if (size_ok and text_only and edge <= EDGE_SUSPICIOUS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
