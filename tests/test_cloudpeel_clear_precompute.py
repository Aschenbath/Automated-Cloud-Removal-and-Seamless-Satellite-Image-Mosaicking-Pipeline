"""CloudPeel must publish complete results when the input is already clear."""

import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.windows import Window


@pytest.fixture
def precompute():
    """Load the website precomputation script from this checkout."""
    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "cloudpeel_precompute", root / "examples/cloudpeel/precompute.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_region(tmp_path, clouds):
    """Write a valid small Step 4 region with varied, nonzero imagery."""
    region = tmp_path / "region"
    region.mkdir()
    for name in ("cloud_database", "cloud_masks", "raw_pan"):
        (region / name).mkdir()
    clean = np.random.default_rng(51).integers(30, 190, (4, 64, 64), dtype=np.uint8)
    transform = from_origin(200000, 2500000, 60, 60)
    for name, data in (
        ("mosaic_xs_raw.tif", clean),
        ("mosaic_pan_raw.tif", clean[:1]),
        ("mosaic_cloudmask_raw.tif", clouds[None]),
        ("land_sea_mask.tif", np.ones((1, 64, 64), np.uint8)),
    ):
        with rasterio.open(
            region / name,
            "w",
            driver="GTiff",
            height=64,
            width=64,
            count=data.shape[0],
            dtype=data.dtype,
            crs="EPSG:3826",
            transform=transform,
        ) as dst:
            dst.write(data)
    windows = np.empty(1, dtype=object)
    windows[0] = Window(0, 0, 64, 64)
    np.save(region / "allWindow.npy", windows)
    np.save(region / "transform.npy", [[200000, 2500000], [200000, 2500000]])
    (region / "ProcessOrder.txt").write_text(
        repr(["a0000001.img", "a0000003.img"]), encoding="utf-8"
    )
    (region / "para_cld.txt").write_text(
        json.dumps(
            {
                "res": 60,
                "pan_res": 60,
                "trueBits": 8,
                "CandiMaskFolderName": "cloud_masks",
            }
        ),
        encoding="utf-8",
    )
    return region


def run_precompute(precompute, monkeypatch, region, out, tolerances):
    """Exercise the real CLI entry point and read its published manifest."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "precompute.py",
            "--region-dir",
            str(region),
            "--out",
            str(out),
            "--name",
            "Synthetic test region",
            "--tolerances",
            *map(str, tolerances),
            "--ssims",
            "0.75",
            "--keep-runs",
        ],
    )
    precompute.main()
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def test_clear_region_completes_real_step4_and_publishes_results(
    precompute, tmp_path, monkeypatch
):
    region = make_region(tmp_path, np.zeros((64, 64), np.uint8))
    out = tmp_path / "data" / "clear"
    out.parent.mkdir()
    existing = {"id": "existing", "path": "data/existing/"}
    (out.parent / "datasets.json").write_text(json.dumps([existing]), encoding="utf-8")

    # This includes real Step 4 subprocesses, reprojection and PNG encoding.
    manifest = run_precompute(precompute, monkeypatch, region, out, [0.05, 0.25])

    assert manifest["cloudy_km2_before"] == 0.0
    assert manifest["candidates"] == []
    assert set(manifest["runs"]) == {"t0.05_s0.75", "t0.25_s0.75"}
    assert np.isfinite(manifest["bounds"]).all()
    for key, run in manifest["runs"].items():
        assert run["patches_filled"] == run["patches_total"] == 0
        assert run["cloudy_area_filled_pct"] == 100.0
        assert run["cloud_left_km2"] == run["flagged_km2"] == 0.0
        assert np.isfinite(run["step4_seconds"])
        assert (out / "img" / f"after_{key}.png").read_bytes() == (
            out / "img" / "before.png"
        ).read_bytes()
        for image in ("clouds_before.png", f"clouds_{key}.png"):
            with Image.open(out / "img" / image) as overlay:
                assert overlay.mode == "RGBA"
                assert not np.asarray(overlay)[..., 3].any()
        for name in precompute.MOSAICS:
            with (
                rasterio.open(region / f"{name}_raw.tif") as raw,
                rasterio.open(out / "runs" / key / f"{name}.tif") as result,
            ):
                assert result.crs == raw.crs
                assert result.transform == raw.transform
                assert result.dtypes == raw.dtypes
                np.testing.assert_array_equal(result.read(), raw.read())
    assert json.loads((out.parent / "datasets.json").read_text(encoding="utf-8")) == [
        existing,
        {
            "id": "clear",
            "region": "Synthetic test region",
            "label": "0 candidate scenes",
            "path": "data/clear/",
        },
    ]


@pytest.mark.parametrize(
    "remaining, flagged, filled, expected_pct, expected_left, expected_flagged",
    [
        (100, 0, 0, 0.0, 0.36, 0.0),
        (50, 0, 1, 50.0, 0.18, 0.0),
        (0, 0, 2, 100.0, 0.0, 0.0),
        (0, 20, 2, 100.0, 0.0, 0.07),
    ],
    ids=["unfilled", "half-filled", "filled", "flagged"],
)
def test_existing_cloud_statistics(
    precompute,
    tmp_path,
    monkeypatch,
    remaining,
    flagged,
    filled,
    expected_pct,
    expected_left,
    expected_flagged,
):
    clouds = np.zeros((64, 64), np.uint8)
    clouds[20:25, 20:30] = 1
    clouds[35:40, 20:30] = 1
    region = make_region(tmp_path, clouds)
    out = tmp_path / "data" / "cloudy"
    calls = []

    def finish_step4(pipeline, run_dir):
        # Isolate filling for these controls; use actual final mask rasters for
        # the native-area statistics, reprojection and published artifacts.
        calls.append(run_dir)
        final = np.zeros_like(clouds)
        indices = np.flatnonzero(clouds)
        final.flat[indices[:remaining]] = 1
        final.flat[indices[remaining : remaining + flagged]] = 10
        with rasterio.open(run_dir / "mosaic_cloudmask.tif", "r+") as dst:
            dst.write(final, 1)
        return filled, 2, 1.25

    monkeypatch.setattr(precompute, "run_step4", finish_step4)
    manifest = run_precompute(precompute, monkeypatch, region, out, [0.25])

    assert len(calls) == 1
    assert manifest["cloudy_km2_before"] == 0.36
    run = manifest["runs"]["t0.25_s0.75"]
    assert run["patches_filled"] == filled
    assert run["patches_total"] == 2
    assert run["cloudy_area_filled_pct"] == expected_pct
    assert run["cloud_left_km2"] == expected_left
    assert run["flagged_km2"] == expected_flagged
