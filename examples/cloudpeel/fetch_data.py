"""Download CloudPeel's precomputed images into site/data/.

The images (about 440 MB) are not kept in git, so that cloning the pipeline
stays small. They are attached to a GitHub release of this repository instead:

    python fetch_data.py            # download and unpack into site/data/
    python fetch_data.py --force    # replace an existing site/data/

Only the Python standard library is needed. To publish a new image set, zip
site/data/ so that the archive holds data/datasets.json, data/<region>/...,
under a new file name, and add it to the existing release:

    cd site && zip -r -X -0 ../cloudpeel-data-v2.zip data
    gh release upload cloudpeel-data-v1 ../cloudpeel-data-v2.zip

then change ASSET below. Do not create a new release for it: every published
release of this repository is archived on Zenodo as a new software version.
"""
import argparse
import pathlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile

REPO_URL = "https://github.com/buckai-observatory/Automated-Cloud-Removal-and-Seamless-Satellite-Image-Mosaicking-Pipeline"
TAG = "cloudpeel-data-v1"
ASSET = "cloudpeel-data.zip"
SITE = pathlib.Path(__file__).resolve().parent / "site"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--force", action="store_true", help="replace an existing site/data/")
    parser.add_argument("--url", default=f"{REPO_URL}/releases/download/{TAG}/{ASSET}",
                        help="archive to download (default: the %(default)s release asset)")
    args = parser.parse_args()

    data = SITE / "data"
    if (data / "datasets.json").exists() and not args.force:
        print(f"{data} already exists; use --force to replace it.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        archive = pathlib.Path(tmp) / ASSET
        print(f"Downloading {args.url} ...")
        try:
            with urllib.request.urlopen(args.url) as r, open(archive, "wb") as f:
                shutil.copyfileobj(r, f)
        except OSError as e:
            sys.exit(f"Download failed: {e}")
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            if "data/datasets.json" not in names or any(
                    n.startswith("/") or ".." in pathlib.PurePosixPath(n).parts for n in names):
                sys.exit("Unexpected archive layout; expected data/datasets.json and data/<region>/...")
            # Finish extraction before removing an installed dataset. A CRC or
            # write error must not replace working images with a partial archive.
            with tempfile.TemporaryDirectory(prefix=".cloudpeel-", dir=SITE) as staged:
                z.extractall(staged)
                if data.exists():
                    shutil.rmtree(data)
                (pathlib.Path(staged) / "data").replace(data)
    print(f"Unpacked into {data}")


if __name__ == "__main__":
    main()
