"""Step 3 must select the Pan companion using the entire XS scene number."""

import json

import numpy as np
import pytest
import rasterio
from rasterio.shutil import copy
from rasterio.transform import from_origin


@pytest.mark.parametrize(
    "scene_numbers",
    [
        (1, 3, 5),
        (1000001, 1000003, 1000005),
        (1234567, 1234569, 1234571),
        (1, 3, 1000005),
    ],
    ids=["leading-zeros", "embedded-zeros", "no-zeros", "later-scene"],
)
def test_main_selects_full_pan_scene_numbers(
    step3, tmp_path, monkeypatch, scene_numbers
):
    monkeypatch.chdir(tmp_path)
    left, top, resolution = 200000, 2500000, 2
    crs = "EPSG:3826"
    initial = from_origin(left, top, resolution, resolution)
    update = from_origin(left + 2 * resolution, top, resolution, resolution)
    scenes = [f"a{number:07d}" for number in scene_numbers]
    (tmp_path / "para_pan.txt").write_text(
        json.dumps(
            {
                "res": resolution,
                "trueBits": 12,
                "StartLetter": "a",
                "upscale_factor": 4,
                "canvas_crs": crs,
                "canvas_x_max": left + 6 * resolution,
                "canvas_y_min": top - 4 * resolution,
            }
        ),
        encoding="utf-8",
    )
    # Step 2 writes the Python representation of the processing-order list.
    (tmp_path / "ProcessOrder.txt").write_text(
        repr([scene + ".img" for scene in scenes]),
        encoding="utf-8",
    )
    np.save("transform.npy", [[left, top], [left, top], [left + 2 * resolution, top]])
    np.save(
        "ImgInd.npy",
        [
            [(1, scenes[1] + ".img", 8, "b1", "b1d")],
            [(1, scenes[2] + ".img", 8, "b1d", "b1")],
        ],
    )
    np.save("allWindow.npy", [])
    np.save("Union_gt.npy", [])
    (tmp_path / "raw_pan").mkdir()
    (tmp_path / "new_pan").mkdir()

    def write_raster(path, data, transform, driver):
        with rasterio.open(
            path,
            "w",
            driver=driver,
            count=1,
            height=4,
            width=4,
            dtype=data.dtype,
            crs=crs,
            transform=transform,
        ) as dst:
            dst.write(data, 1)

    expected_pan_names = []
    for number, value, transform in zip(
        scene_numbers, (1000, 2000, 3000), (initial, initial, update)
    ):
        name = f"A{number + 1:07d}.tif"
        expected_pan_names.append(name)
        write_raster(
            tmp_path / "raw_pan" / name,
            np.full((4, 4), value, np.uint16),
            transform,
            "GTiff",
        )

    seamline = np.tile(np.array([0, 0.5, 1, 1], np.float32), (4, 1))
    write_raster(
        scenes[0] + scenes[1] + "_seamline_polygon.img", seamline, initial, "HFA"
    )
    write_raster(scenes[2] + "_seamline_polygon.img", seamline, update, "HFA")

    selected = []

    def clip_pan(source, destination, target_crs, bounds):
        # These real rasters already occupy the requested clipping grid, so
        # copying them is the identity case of the external gdalwarp command.
        with rasterio.open(source) as src:
            assert src.crs.to_string() == target_crs
            assert tuple(src.bounds) == tuple(bounds)
        selected.append(source.name)
        copy(source, destination, driver="GTiff")

    monkeypatch.setattr(step3, "clip_pan", clip_pan)
    step3.main()

    assert selected == expected_pan_names
    with rasterio.open("mosaic_pan.tif") as mosaic:
        assert mosaic.transform == initial
        assert mosaic.crs.to_epsg() == 3826
        assert mosaic.dtypes == ("uint16",)
        expected = np.tile([1000, 1500, 2000, 2500, 3000, 3000], (4, 1))
        np.testing.assert_array_equal(mosaic.read(1), expected)
