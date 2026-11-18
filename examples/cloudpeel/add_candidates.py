"""Add more Sentinel-2 dates to a demo region's cloud-filling candidate pool.

The Sentinel-2 demo fills clouds from three almost cloud-free scenes, so Step 4's
``cloud_tolerance`` never matters there. This script copies the region's Step 4
folder and adds partly cloudy dates as extra candidates. The pipeline then
has to choose between a better-matching but partly cloudy scene and a clearer
one, and the tolerance setting decides.

Scenes are converted exactly as the demo does it, by reusing
``prepare_scene`` from ``examples/sentinel2_demo/run_demo.py``.

Usage:
    python add_candidates.py --region-dir ../demo_output/step4 \
        --out work/taichung_more \
        --items S2A_51QTG_20231002_0_L2A S2A_51QTG_20231104_0_L2A
"""
import argparse
import json
import importlib.util
import pathlib
import shutil

import numpy as np
import rasterio

REPO = pathlib.Path(__file__).resolve().parents[2]  # the pipeline repository


def load_demo(pipeline):
    path = pipeline / "examples" / "sentinel2_demo" / "run_demo.py"
    spec = importlib.util.spec_from_file_location("run_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region-dir", type=pathlib.Path, required=True)
    parser.add_argument("--pipeline", type=pathlib.Path, default=REPO,
                        help="Clone of the cloud-removal pipeline (default: this repository)")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--items", nargs="+", required=True, help="Earth Search item ids")
    parser.add_argument("--min-cloud", type=float, default=0.03,
                        help="Drop scenes with less cloud than this over the area")
    parser.add_argument("--min-coverage", type=float, default=0.95,
                        help="Drop scenes whose data covers less of the area than this")
    parser.add_argument("--max-cloud", type=float, default=0.80,
                        help="Drop scenes with more cloud than this over the area")
    parser.add_argument("--first-number", type=int, default=107,
                        help="Number of the first new scene name (odd; its Pan scene gets +1)")
    args = parser.parse_args()
    demo = load_demo(args.pipeline.resolve())
    region, out = args.region_dir.resolve(), args.out.resolve()

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(region, out, ignore=shutil.ignore_patterns(
        "mosaic_xs.tif", "mosaic_pan.tif", "mosaic_cloudmask.tif"))
    db, masks, pan = out / "cloud_database", out / "cloud_masks", out / "raw_pan"

    number = args.first_number
    added = {}
    for item in args.items:
        name = f"a{number:07d}"
        cloud = demo.prepare_scene(name, item, demo.AOI, db, masks, pan)
        with rasterio.open(db / f"{name}.img") as src:
            coverage = float(np.mean(src.read(1) > 0))
        keep = coverage >= args.min_coverage and args.min_cloud <= cloud <= args.max_cloud
        print(f"    data covers {coverage:.0%} of the area, cloud {cloud:.0%} "
              f"-> {'kept' if keep else 'dropped'}")
        if keep:
            added[name] = item
            number += 2
        else:
            for f in [*db.glob(f"{name}.img*"), *masks.glob(f"{name}_*"),
                      *pan.glob(f"{demo.pan_name(name)}.*")]:
                f.unlink()
    print(f"Candidate pool now: {sorted(p.name for p in db.glob('*.img'))}")
    # Record which new scene is which date (read by extras.py).
    (out / "added.json").write_text(json.dumps(added, indent=1))


if __name__ == "__main__":
    main()
