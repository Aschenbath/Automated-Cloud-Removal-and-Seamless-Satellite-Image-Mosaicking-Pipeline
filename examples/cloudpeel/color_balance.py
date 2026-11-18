"""Simple colour balancing of the mosaic strips before Step 2.

The pipeline's Step 1 (ERDAS IMAGINE) normally balances every scene against
reference imagery. Without ERDAS, the README says to start at Step 2 with
scenes "color-balanced by any other tool". This module is such a tool, and a
deliberately simple one. For each strip and band it fits a gain and offset
that match the strip's mean and standard deviation to a clear reference date
over the pixels that are clear in both. This removes most of the haze and
illumination differences between dates.

The originals are kept in ``scenes_original/`` and ``raw_pan_original/``, and
balancing always starts from them, so running it again gives the same result.
"""
import pathlib
import shutil

import numpy as np
import rasterio
from rasterio.windows import from_bounds


def _gain_offset(src, ref, mask):
    s, r = src[mask].astype(np.float64), ref[mask].astype(np.float64)
    gain = r.std() / max(s.std(), 1e-6)
    return gain, r.mean() - gain * s.mean()


def _apply(band, gain, offset, max_dn):
    out = np.clip(np.round(band * gain + offset), 1, max_dn).astype(band.dtype)
    out[band == 0] = 0
    return out


def _read_matching(path, bounds, shape):
    """Read the part of *path* covering *bounds* (same grid, so no resampling)."""
    with rasterio.open(path) as ds:
        win = from_bounds(*bounds, ds.transform).round_offsets().round_lengths()
        data = ds.read(window=win, boundless=True, fill_value=0)
    assert data.shape[-2:] == shape, (path, data.shape, shape)
    return data


def balance(data, primary_names, reference, max_dn, pan_name):
    """Colour-balance the mosaic strips in *data* against candidate *reference*."""
    data = pathlib.Path(data)
    for sub in ("scenes", "raw_pan"):
        if not (data / f"{sub}_original").exists():
            shutil.copytree(data / sub, data / f"{sub}_original")

    ref_xs = data / "candidates" / f"{reference}.img"
    ref_cloud = data / "cloud_masks" / f"{reference}_cloud.tif"
    report = {}
    for name in primary_names:
        src_path = data / "scenes_original" / f"{name}.img"
        with rasterio.open(src_path) as ds:
            xs, profile, bounds = ds.read(), ds.profile, ds.bounds
        shape = xs.shape[-2:]
        ref = _read_matching(ref_xs, bounds, shape)
        with rasterio.open(data / "cloud_masks" / f"{name}_cloud.tif") as ds:
            cloud = ds.read(1) > 0
        rcloud = _read_matching(ref_cloud, bounds, shape)[0] > 0
        mask = np.all(xs > 0, axis=0) & np.all(ref > 0, axis=0) & ~cloud & ~rcloud
        if mask.sum() < 1000:
            print(f"  {name}: too few clear shared pixels, left as is")
            continue
        fits = [_gain_offset(xs[b], ref[b], mask) for b in range(xs.shape[0])]
        balanced = np.stack([_apply(xs[b], *fits[b], max_dn) for b in range(xs.shape[0])])
        with rasterio.open(data / "scenes" / f"{name}.img", "w", **profile) as ds:
            ds.write(balanced)

        # Pan (mean of the visible bands, at twice the resolution): use the
        # mean of the visible-band fits, which is what the Pan stand-in is made of.
        pan_file = f"{pan_name(name)}.tif"
        with rasterio.open(data / "raw_pan_original" / pan_file) as ds:
            pan, pan_profile = ds.read(1), ds.profile
        gain = np.mean([f[0] for f in fits[:3]])
        offset = np.mean([f[1] for f in fits[:3]])
        with rasterio.open(data / "raw_pan" / pan_file, "w", **pan_profile) as ds:
            ds.write(_apply(pan, gain, offset, max_dn), 1)
        report[name] = [(round(g, 3), round(o, 1)) for g, o in fits]
        print(f"  {name}: gain/offset per band {report[name]}")
    return report
