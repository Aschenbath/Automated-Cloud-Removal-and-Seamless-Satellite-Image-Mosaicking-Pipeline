"""Exercise real local downloads and ZIP extraction without the image release."""
import importlib.util
from pathlib import Path
import sys
import zipfile

import pytest


@pytest.fixture
def fetch_data(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "examples/cloudpeel/fetch_data.py"
    spec = importlib.util.spec_from_file_location("cloudpeel_fetch_data", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.setattr(module, "SITE", site)
    return module


def make_archive(path, corrupt=False):
    """Create a stored ZIP and optionally break an image's actual CRC."""
    payload = b"replacement image bytes"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("data/datasets.json", '[{"id": "new-region"}]')
        archive.writestr("data/new-region/img/before.png", payload)
    if corrupt:
        raw = path.read_bytes()
        assert raw.count(payload) == 1
        path.write_bytes(raw.replace(payload, b"X" + payload[1:]))
    return path.as_uri()


@pytest.mark.parametrize("force", [True, False], ids=["forced-update", "partial-install"])
def test_corrupt_archive_preserves_existing_data(fetch_data, tmp_path, monkeypatch, force):
    data = fetch_data.SITE / "data"
    data.mkdir()
    existing = data / "saved-image.png"
    existing.write_bytes(b"old image still usable")
    if force:
        (data / "datasets.json").write_text('[{"id": "old-region"}]', encoding="utf-8")
    before = {path.relative_to(data): path.read_bytes() for path in data.rglob("*") if path.is_file()}
    url = make_archive(tmp_path / "broken.zip", corrupt=True)
    argv = ["fetch_data.py", "--url", url] + (["--force"] if force else [])
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        fetch_data.main()

    after = {path.relative_to(data): path.read_bytes() for path in data.rglob("*") if path.is_file()}
    assert after == before
    assert set(fetch_data.SITE.iterdir()) == {data}


@pytest.mark.parametrize("existing", [True, False], ids=["replace", "first-install"])
def test_valid_archive_installs_complete_data(fetch_data, tmp_path, monkeypatch, existing):
    data = fetch_data.SITE / "data"
    if existing:
        data.mkdir()
        (data / "datasets.json").write_text("[]", encoding="utf-8")
        (data / "obsolete.png").write_bytes(b"old image")
    url = make_archive(tmp_path / "valid.zip")
    monkeypatch.setattr(sys, "argv", ["fetch_data.py", "--force", "--url", url])

    fetch_data.main()

    assert (data / "datasets.json").read_text(encoding="utf-8") == '[{"id": "new-region"}]'
    assert (data / "new-region/img/before.png").read_bytes() == b"replacement image bytes"
    assert not (data / "obsolete.png").exists()
    assert set(fetch_data.SITE.iterdir()) == {data}


def test_existing_dataset_without_force_is_unchanged(fetch_data, tmp_path, monkeypatch):
    data = fetch_data.SITE / "data"
    data.mkdir()
    (data / "datasets.json").write_bytes(b"original manifest")
    monkeypatch.setattr(sys, "argv", ["fetch_data.py", "--url", (tmp_path / "missing.zip").as_uri()])

    fetch_data.main()

    assert (data / "datasets.json").read_bytes() == b"original manifest"
