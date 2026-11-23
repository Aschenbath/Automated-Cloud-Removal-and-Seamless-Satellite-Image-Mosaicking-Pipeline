"""Documentation website: README lines that link to the site itself."""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def build_site():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "site" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_home_page_links_are_dropped_and_cloudpeel_links_kept(build_site):
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    kept = build_site.drop_home_links(text)
    home = build_site.SITE_URL
    cloudpeel = home + "cloudpeel/"
    # the "Documentation website" badge and line link to the home page itself
    assert f"]({home})" in text and f"<{home}>" in text
    assert f"]({home})" not in kept and f"<{home}>" not in kept
    # every line that links to CloudPeel stays, e.g. the "Try it" list at the top
    cloudpeel_lines = [line for line in text.splitlines() if cloudpeel in line]
    assert len(cloudpeel_lines) >= 2
    assert all(line in kept.splitlines() for line in cloudpeel_lines)
    assert "nothing to install" in kept
