"""Iterative mosaics accept Shapely 2 footprints with more than two crossings."""
import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely import wkt
from shapely.geometry import Polygon, box


@pytest.mark.parametrize("footprint, crossings, difference_type, expected_points, retained", [
    pytest.param(box(100, 180, 110, 190), 2, "Polygon", {(110, 184), (104, 190)}, None,
                 id="two-crossings"),
    pytest.param(
        Polygon([(100, 182), (110, 182), (110, 187), (102, 187),
                 (102, 193), (110, 193), (110, 198), (100, 198)]),
        4, "Polygon", None, None, id="four-crossings-polygon",
    ),
    pytest.param(box(108, 180, 111, 200), 4, "MultiPolygon", {(111, 184), (111, 196)},
                 box(111, 184, 116, 196), id="four-crossings-multipart"),
])
def test_iterative_footprint_intersections(
    step2, tmp_path, monkeypatch, footprint, crossings, difference_type, expected_points, retained,
):
    monkeypatch.chdir(tmp_path)
    tool_dir = tmp_path / "NSPO_GRID_vectorization"
    tool_dir.mkdir()
    transform = from_origin(100, 200, 1, 1)
    incoming = box(104, 184, 116, 196)

    def write_scene(path, geometry):
        mask = rasterize([(geometry, 1)], out_shape=(20, 20), transform=transform,
                         fill=0, dtype="uint16")
        data = np.stack([mask * 100, mask * 200, mask * 300])
        with rasterio.open(path, "w", driver="GTiff", width=20, height=20, count=3,
                           dtype="uint16", crs="EPSG:3826", transform=transform,
                           nodata=0) as dst:
            dst.write(data)
        # Use the pipeline's real raster polygonization; no GDAL executable is needed.
        step2.polygonize_valid_area(str(path))
        return data

    scene_path = tool_dir / "scene.tif"
    mosaic_path = tmp_path / "mosaic.tif"
    scene_data = write_scene(scene_path, incoming)
    mosaic_data = write_scene(mosaic_path, footprint)
    running = gpd.read_file(tmp_path / "mosaic.temp.shp")
    scene_footprint = gpd.read_file(tool_dir / "scene.temp.shp").geometry.iloc[0]
    running_footprint = running.geometry.iloc[0]
    points = scene_footprint.boundary.intersection(running_footprint.boundary)
    assert scene_footprint.is_valid and running_footprint.is_valid
    assert len(points.geoms) == crossings
    assert scene_footprint.difference(running_footprint).geom_type == difference_type

    result = step2.find_raster_intersect_for_mosaic(
        str(scene_path), str(mosaic_path), transform, 1, 1, running,
    )

    assert len(set(result[5])) == 2
    assert all(points.covers(wkt.loads(point)) for point in result[5])
    if expected_points is not None:
        assert {(wkt.loads(point).x, wkt.loads(point).y) for point in result[5]} == expected_points
    np.testing.assert_array_equal(result[0], np.moveaxis(scene_data[::-1], 0, -1))
    np.testing.assert_array_equal(result[1], np.moveaxis(mosaic_data[::-1], 0, -1))
    np.testing.assert_array_equal(result[8], (scene_data[0] > 0) | (mosaic_data[0] > 0))
    # Only the larger newly exposed component is retained when the difference is multipart.
    expected_union = running_footprint.union(scene_footprint if retained is None else retained)
    assert result[-1].geometry.iloc[0].equals(expected_union)
    saved_union = gpd.read_file(tmp_path / "res_union_new.shp")
    assert saved_union.crs == running.crs
    assert saved_union.geometry.iloc[0].equals(expected_union)
