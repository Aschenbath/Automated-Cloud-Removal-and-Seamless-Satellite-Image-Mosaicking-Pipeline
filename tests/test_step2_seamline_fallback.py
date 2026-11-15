"""Step 2 finds a seamline even when masked pixels split the overlap."""
import networkx as nx
import numpy as np
import pytest


def split_overlap(h=9, w=9, wall_row=4):
    """Two identical scenes with a strong vertical edge at column 4.

    A full row of zeros (masked or no-data, e.g. snow or cloud removed from
    the overlap) separates the two seamline endpoints, so no path through
    valid pixels exists.
    """
    img = np.full((h, w), 10, dtype=np.uint8)
    img[:, 5:] = 200
    img[wall_row, :] = 0
    source = 0 * w + 4 + 1                      # node ids are 1-based, row-major
    target = (h - 2) * w + 4 + 1
    return img, (source, target)


@pytest.mark.parametrize("method", ["a6c", "a7c", "a6c_int"])
def test_split_overlap_still_raises_without_fallback(step2, method):
    img, ends = split_overlap()
    with pytest.raises(nx.NetworkXNoPath):
        step2.buildGraph(img, img.copy(), *img.shape, method, ends)


@pytest.mark.parametrize("method", ["a6c", "a7c", "a6c_int"])
def test_fallback_crosses_the_masked_row_once(step2, method, capsys):
    img, ends = split_overlap()
    h, w = img.shape
    seam = step2.buildGraph(img, img.copy(), h, w, method, ends, masked_fallback=True)
    assert "WARNING" in capsys.readouterr().out
    # The seam joins both endpoints and runs along the image edge (columns 4-5).
    assert seam[0, 4] == 1 and seam[h - 2, 4] == 1
    assert set(np.nonzero(seam)[1]) <= {4, 5}
    # It crosses the masked row at a single pixel, the fewest possible.
    assert seam[4].sum() == 1
    assert set(range(h - 1)) <= set(np.nonzero(seam)[0])


@pytest.mark.parametrize("method", ["a6", "a7", "a6c", "a7c", "a6c_int", "a7c_int"])
def test_fallback_leaves_valid_seamlines_unchanged(step2, method):
    rng = np.random.default_rng(7)
    img1 = rng.integers(1, 255, (12, 15), dtype=np.uint8)
    img2 = rng.integers(1, 255, (12, 15), dtype=np.uint8)
    img1[5, 3:12] = 0                            # masked pixels the path can go round
    ends = (1 * 15 + 2 + 1, 10 * 15 + 12 + 1)
    plain = step2.buildGraph(img1, img2, 12, 15, method, ends)
    fallback = step2.buildGraph(img1, img2, 12, 15, method, ends, masked_fallback=True)
    np.testing.assert_array_equal(plain, fallback)


def test_endpoint_outside_the_grid_is_a_clear_error(step2):
    img, _ = split_overlap()
    with pytest.raises(step2.SeamlineNotFoundError, match="outside"):
        step2.buildGraph(img, img.copy(), *img.shape, "a6c", (5, 10_000), masked_fallback=True)


@pytest.mark.parametrize("ends", [(), (5,), (5, 40, 70)])
def test_wrong_number_of_endpoints_names_both_scenes(step2, ends):
    img = np.full((9, 9), 100, dtype=np.uint8)
    with pytest.raises(step2.SeamlineNotFoundError, match=rf"a0000001\.img.*a0000003\.img.*found {len(ends)}"):
        step2.find_seamline(5, img, img.copy(), [4, 4], [0, 8], "a6c", list(ends),
                            "a0000001.img", "a0000003.img")


def test_find_seamline_matches_clip_and_build_graph(step2):
    rng = np.random.default_rng(11)
    img1 = rng.integers(1, 255, (30, 30), dtype=np.uint8)
    img2 = rng.integers(1, 255, (30, 30), dtype=np.uint8)
    fr, fc = [0, 29], [15, 15]
    ends = [0 * 30 + 15 + 1, 29 * 30 + 15 + 1]
    expected = step2.buildGraph(*step2.clipImg(5, img1, img2, fr, fc), "a6c_int", ends)
    seam = step2.find_seamline(5, img1, img2, fr, fc, "a6c_int", ends, "a.img", "b.img")
    np.testing.assert_array_equal(seam, expected)
