"""Draw the seamlines found by Step 2 as a red overlay for the website.

Where Step 2 saved the raw seam path it found (``*_seamline.img``), that path is
drawn, so it shows how the cut follows roads, rivers and other high-contrast
edges (at the resolution Step 2 searched, ``res * resampleTo``). For pairs where
Step 2 saved only the feathered blend weights (``*_seamline_polygon.img``:
1 = this side, 0 = the other), the 0.5 contour of the weights is drawn
instead; it is smoother than the raw path. The script traces these lines,
reprojects it onto the same Web Mercator grid as the quicklooks from
``precompute.py``, and saves ``img/seams.png``. It also marks the result set's
``manifest.json`` so the page offers the layer.

Usage:
    python seams.py --step2-dir ../demo_output/step2 \
        --mosaic ../demo_output/step4/mosaic_xs_raw.tif --out site/data/taichung
"""
import argparse
import json
import pathlib

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy.ndimage import binary_dilation

WEB_CRS = "EPSG:3857"
RED = (230, 20, 20, 255)


def seam_line(weights):
    """Pixels on the 0.5 contour of a blend-weight raster."""
    side = weights >= 0.5
    edge = np.zeros_like(side)
    edge[:-1] |= side[:-1] != side[1:]
    edge[:, :-1] |= side[:, :-1] != side[:, 1:]
    # Keep only crossings inside the feathered band, which excludes jumps at
    # the raster's own edges.
    band = binary_dilation((weights > 0) & (weights < 1), iterations=2)
    return edge & band


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step2-dir", type=pathlib.Path, required=True)
    parser.add_argument("--mosaic", type=pathlib.Path, required=True,
                        help="The mosaic the quicklooks were made from (defines the grid)")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="Result-set folder")
    parser.add_argument("--width", type=int, default=2, help="Line width in output pixels")
    args = parser.parse_args()

    with rasterio.open(args.mosaic) as src:
        transform, width, height = calculate_default_transform(
            src.crs, WEB_CRS, src.width, src.height, *src.bounds)
    lines = np.zeros((height, width), np.uint8)

    files = sorted(args.step2_dir.glob("*_seamline_polygon.img"))
    for f in files:
        raw = f.with_name(f.name.replace("_seamline_polygon.img", "_seamline.img"))
        source = raw if raw.exists() else f
        with rasterio.open(source) as src:
            if source == raw:
                line = (src.read(1) > 0).astype(np.uint8)
            else:
                line = seam_line(src.read(1).astype(np.float32)).astype(np.uint8)
            dst = np.zeros_like(lines)
            reproject(line, dst, src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=WEB_CRS, resampling=Resampling.max)
        lines |= dst
        print(f"{source.name}: {int(line.sum())} seam pixels "
              f"({'raw path' if source == raw else 'blend centre'})")

    if args.width > 1:
        lines = binary_dilation(lines > 0, iterations=args.width - 1)
    rgba = np.zeros((height, width, 4), np.uint8)
    rgba[lines > 0] = RED
    out_img = args.out / "img" / "seams.png"
    Image.fromarray(rgba, "RGBA").save(out_img, optimize=True)

    manifest_path = args.out / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["seams"] = len(files)
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"Wrote {out_img} ({len(files)} seams)")


if __name__ == "__main__":
    main()
