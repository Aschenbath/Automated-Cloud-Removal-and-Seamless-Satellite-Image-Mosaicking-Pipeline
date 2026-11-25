"""Run real Step 2 mosaics whose flood-filled components fall below 1000 pixels.

The synthetic tilted footprints use the Sentinel-2 demo's geometry helpers.
Input enumeration is fixed, and Rasterio supplies GDAL's matching-CRS copy.
Polygonization, seamline search, flood fill, component selection and blending
all run normally.
"""
import ast
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.shutil import copy
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from rasterio.windows import Window


@pytest.fixture(scope="module")
def demo():
    source = Path(__file__).resolve().parents[1] / "examples/sentinel2_demo/run_demo.py"
    spec = importlib.util.spec_from_file_location("run_demo", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_mosaic(step2, demo, directory, monkeypatch, scale, third=False):
    """Write clear four-band scenes and return the mosaic and observed masks."""
    (directory / "cloud_masks").mkdir(parents=True)
    (directory / "NSPO_GRID_vectorization").mkdir()
    rectangles = [(200000 + cx * scale, 2500000 + cy * scale, 400 * scale, 900 * scale)
                  for cx, cy in ((500, 750), (750, 780))]
    if third:
        # This 40 x 20 crop has two boundary crossings with the running mosaic.
        rectangles.append((201900, 2501700, 300, 600))
    scene_paths = []
    for index, rectangle in enumerate(rectangles):
        name = f"a{1 + 2 * index:07d}"
        corners, bounds = demo.footprint(*rectangle)
        valid = demo.inside(corners, bounds, demo.XS_RES)
        transform, width, height = demo.grid(bounds, demo.XS_RES)
        rows, cols = np.indices((height, width))
        x = transform.c + (cols + 0.5) * transform.a
        y = transform.f + (rows + 0.5) * transform.e
        # The same analytic ground field in every scene, in 12-bit DN.
        field = 700 + (x - 200000) / 20 * 4 + (2503000 - y) / 20 * 6
        data = np.stack([np.where(valid, field + band * 100, 0)
                         for band in range(4)]).astype(np.uint16)
        path = directory / f"{name}.img"
        demo.write(path, data, bounds, demo.XS_RES, "HFA")
        demo.write(directory / "cloud_masks" / f"{name}_cloud.tif",
                   np.zeros(valid.shape, np.uint8), bounds, demo.XS_RES, "GTiff")
        scene_paths.append(path)

    parameters = {"path_method": "a6c", "res": "20", "pan_res": "10", "resampleTo": "1",
                  "trueBits": "12", "imgPath": str(directory), "kernel": "3",
                  "canvas_crs": demo.CRS, "canvas_x_max": str(200000 + 1600 * scale),
                  "canvas_y_min": "2500000"}
    (directory / "para.txt").write_text(json.dumps(parameters), encoding="utf-8")
    component_masks, component_sizes, blend_masks = [], [], []
    connected_components = step2.cv2.connectedComponents
    blend_mask = step2.blendMask

    def observe_components(mask, *args, **kwargs):
        count, labels = connected_components(mask, *args, **kwargs)
        component_masks.append(mask.copy())
        component_sizes.append([int(np.count_nonzero(labels == label))
                                for label in range(1, count)])
        return count, labels

    def observe_blend(blend_pixels, mask):
        blend_masks.append(mask.copy())
        return blend_mask(blend_pixels, mask)

    monkeypatch.setattr(step2, "assign_crs_copy", lambda src, dst, crs: copy(src, dst, driver="GTiff"))
    # This fixture exercises the initial pair before the later small crop.
    # Filesystem enumeration order varies between platforms and test runs.
    listdir = step2.listdir
    monkeypatch.setattr(step2, "listdir", lambda path: sorted(listdir(path)))
    monkeypatch.setattr(step2.cv2, "connectedComponents", observe_components)
    monkeypatch.setattr(step2, "blendMask", observe_blend)
    monkeypatch.chdir(directory)
    step2.main()

    order = ast.literal_eval((directory / "ProcessOrder.txt").read_text())
    assert order == [path.name for path in scene_paths]
    blend_orders = np.load(directory / "ImgInd.npy", allow_pickle=True)
    assert all(np.isfinite(float(row[2])) for selection in blend_orders for row in selection)
    with rasterio.open(directory / "mosaic_xs.tif") as src:
        output = src.read()
        assert src.count == 4 and src.dtypes == ("uint16",) * 4
        assert src.crs.to_string() == demo.CRS and src.nodata == 0
        footprint = np.zeros(src.shape, np.uint8)
        for path in scene_paths:
            with rasterio.open(path) as scene:
                layer = np.zeros(src.shape, np.uint8)
                reproject((scene.read(1) > 0).astype(np.uint8), layer,
                          src_transform=scene.transform, src_crs=scene.crs,
                          dst_transform=src.transform, dst_crs=src.crs,
                          resampling=Resampling.nearest)
                footprint |= layer
    # Every source pixel survives, and nothing is painted outside their union.
    np.testing.assert_array_equal(np.any(output > 0, axis=0), footprint > 0)
    assert np.all(output[:, footprint > 0] > 0)
    assert output.max() < 4096
    return output, component_masks, component_sizes, blend_masks


@pytest.mark.parametrize("scale,third,small_index", [
    pytest.param(0.75, False, 0, id="initial-pair"),
    pytest.param(2, True, 1, id="iterative-crop"),
])
def test_small_components_keep_the_flood_filled_mask(
    step2, demo, tmp_path, monkeypatch, scale, third, small_index,
):
    _, masks, sizes, blends = run_mosaic(step2, demo, tmp_path, monkeypatch, scale, third)
    assert len(sizes) == small_index + 1
    assert len(sizes[small_index]) == 1 and 0 < sizes[small_index][0] <= 1000
    np.testing.assert_array_equal(blends[small_index], masks[small_index])
    if third:
        assert max(sizes[0]) > 1000  # The initial pair already completed normally.


def test_larger_component_remains_selected(step2, demo, tmp_path, monkeypatch):
    _, masks, sizes, blends = run_mosaic(step2, demo, tmp_path, monkeypatch, 2)
    assert len(sizes) == 1 and len(sizes[0]) == 1 and sizes[0][0] > 1000
    np.testing.assert_array_equal(blends[0], masks[0])


def test_empty_blend_mask_stays_empty(step2):
    mask = np.zeros((40, 35), np.uint8)
    weights = step2.blendMask(57, mask)
    np.testing.assert_array_equal(weights, np.zeros(mask.shape, np.float32))
    assert not mask.any()


@pytest.mark.parametrize("iterative", [False, True], ids=["initial", "iterative"])
@pytest.mark.parametrize("weights,first_coverage,second_coverage", [
    pytest.param([[0.5] * 3] * 2, (0, 0), (0, 0), id="no-pure-weights"),
    pytest.param([[0] * 3] * 2, (round(2 / 3, 9), 0), (round(2 / 3, 9), 0), id="no-ones"),
    pytest.param([[1] * 3] * 2, (0, round(2 / 3, 9)), (0, round(2 / 3, 9)), id="no-zeros"),
    pytest.param([[0, 0, 1], [1, 0.5, 1]], (0.5, round(2 / 3, 9)), (0.5, 1), id="nonempty"),
])
def test_blend_order_coverage_for_empty_and_nonempty_weight_classes(
    step2, tmp_path, monkeypatch, iterative, weights, first_coverage, second_coverage,
):
    transform = from_origin(100, 200, 1, 1)
    first = np.array([[10, 0, 30], [0, 50, 60]], np.uint16)
    second = np.array([[0, 20, 30], [40, 0, 60]], np.uint16)
    paths = [tmp_path / "incoming.tif", tmp_path / "running.tif"]
    for path, data in zip(paths, (first, second)):
        with rasterio.open(path, "w", driver="GTiff", width=3, height=2, count=1,
                           dtype="uint16", crs="EPSG:3826", transform=transform) as dst:
            dst.write(data, 1)
    weights = np.array(weights, np.float32)
    if iterative:
        monkeypatch.setattr(step2, "union_gt", transform, raising=False)
        monkeypatch.setattr(step2, "res", 1, raising=False)
        placed, running, *coverage = step2.blend_preprocess_order_for_mosaic(
            str(paths[0]), str(paths[1]), weights, Window(0, 0, 3, 2),
        )
        np.testing.assert_array_equal(running, second)
        assert tuple(coverage) == first_coverage + second_coverage
    else:
        placed, *coverage = step2.blend_preprocess_for_order(str(paths[0]), weights, 1, transform)
        assert tuple(coverage) == first_coverage
    np.testing.assert_array_equal(placed, first)
