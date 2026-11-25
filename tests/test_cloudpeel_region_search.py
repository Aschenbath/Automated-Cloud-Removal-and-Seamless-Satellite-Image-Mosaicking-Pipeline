"""CloudPeel region selection consumes complete STAC searches over local HTTP."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError

import pytest
from shapely.geometry import box


def item(name, date, complete=True):
    footprint = box(-1, -1, 2, 2) if complete else box(0, 0, 0.5, 0.5)
    return {"type": "Feature", "id": name, "geometry": footprint.__geo_interface__,
            "properties": {"datetime": date + "T12:00:00Z"}, "assets": {}}


@pytest.fixture
def search_server(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "examples" / "cloudpeel"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("cloudpeel_region_search", directory / "make_region.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pages, requests = {}, []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests.append({"method": self.command, "path": self.path,
                             "body": json.loads(raw) if raw else None,
                             "headers": {k.lower(): v for k, v in self.headers.items()}})
            status, page = pages.get(self.path, (404, {}))
            payload = json.dumps(page).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/geo+json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        origin = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setattr(module, "SEARCH", origin + "/catalog/search")
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield module, pages, requests, origin
        finally:
            server.shutdown()
            thread.join()


def first_items():
    return [item("cloudy-first", "2024-03-03"), item("duplicate-first", "2024-03-03"),
            item("partial-early", "2024-03-01", complete=False)]


@pytest.mark.parametrize("method, merge, relative", [
    pytest.param(None, False, True, id="default-get-relative"),
    pytest.param("GET", False, False, id="get-absolute"),
    pytest.param("POST", False, False, id="post-replacement"),
    pytest.param("POST", True, True, id="post-merge-relative"),
])
def test_search_follows_stac_pages(search_server, method, merge, relative):
    module, pages, requests, origin = search_server

    def next_link(page):
        href = ("pages/2" if page == 2 else "3") if relative else f"{origin}/catalog/pages/{page}"
        link = {"rel": "next", "href": href, "headers": {"X-Page": str(page)}}
        if method is not None:
            link["method"] = method
        if page == 2:
            link["headers"]["X-Only-Second"] = "discard-on-next-page"
        if method == "POST":
            link["body"] = {"token": str(page)}
            if page == 2:
                link["body"]["page_only"] = "discard-on-next-page"
            link["merge"] = merge
        return link

    pages["/catalog/search"] = (200, {"features": first_items(), "links": [next_link(2)]})
    # An empty intermediate page is still followed if it advertises another page.
    pages["/catalog/pages/2"] = (200, {"features": [], "links": [next_link(3)]})
    pages["/catalog/pages/3"] = (200, {"features": [
        item("clear-later-page", "2024-03-01"), item("duplicate-later", "2024-03-03"),
        item("partial-later", "2024-03-02", complete=False),
    ], "links": []})

    result = module.search((0, 0, 1, 1), "2024-03-01", "2024-03-31")

    assert [entry["id"] for entry in result] == ["clear-later-page", "cloudy-first"]
    assert len(requests) == 3
    assert requests[0]["method"] == "POST"
    original = requests[0]["body"]
    assert original["datetime"] == "2024-03-01T00:00:00Z/2024-03-31T23:59:59Z"
    assert original["collections"] == ["sentinel-2-l2a"]
    for page, request in enumerate(requests[1:], start=2):
        assert request["method"] == (method or "GET")
        assert request["headers"]["x-page"] == str(page)
        if method == "POST":
            expected = {**original, "token": str(page)} if merge else {"token": str(page)}
            if page == 2:
                expected["page_only"] = "discard-on-next-page"
            assert request["body"] == expected
            assert request["headers"]["content-type"] == "application/json"
        else:
            assert request["body"] is None
    assert "x-only-second" not in requests[-1]["headers"]


def test_single_page_keeps_coverage_and_date_deduplication(search_server):
    module, pages, requests, _ = search_server
    pages["/catalog/search"] = (200, {"features": first_items()})
    result = module.search((0, 0, 1, 1), "2024-03-01", "2024-03-31")
    assert [entry["id"] for entry in result] == ["cloudy-first"]
    assert len(requests) == 1


def test_later_page_error_does_not_return_partial_search(search_server):
    module, pages, requests, _ = search_server
    pages["/catalog/search"] = (200, {"features": first_items(),
        "links": [{"rel": "next", "href": "pages/2"}]})
    pages["/catalog/pages/2"] = (503, {})
    with pytest.raises(HTTPError) as error:
        module.search((0, 0, 1, 1), "2024-03-01", "2024-03-31")
    assert error.value.code == 503
    assert len(requests) == 2
