"""Tests for the PhotoHandler Description node.

A lightweight local HTTP server stands in for PhotoHandler so the node can be
exercised end to end without any external dependencies. Run with::

    python test_photohandler_node.py

or under pytest::

    pytest test_photohandler_node.py
"""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from photohandler_node import PhotoHandlerDescription


class _FakeHandler(BaseHTTPRequestHandler):
    # Map of image path -> response spec used by the running server.
    responses = {}

    def log_message(self, *args):  # silence the test server
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/assets/by-path/description":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        path = params.get("path", [""])[0]
        spec = self.responses.get(path)

        if spec is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")
            return

        status, body = spec
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def _start_server(responses):
    _FakeHandler.responses = responses
    server = HTTPServer(("127.0.0.1", 0), _FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _run_node(monkeypatch_env, server):
    host, port = server.server_address
    monkeypatch_env("PHOTOHANDLER_URL", "http://{}:{}".format(host, port))
    return PhotoHandlerDescription().get_description


def test_returns_description_from_object(monkeypatch):
    server = _start_server(
        {"/photos/cat.jpg": (200, json.dumps({"description": "a cat"}))}
    )
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/photos/cat.jpg") == ("a cat",)
    finally:
        server.shutdown()


def test_returns_description_from_bare_string(monkeypatch):
    server = _start_server({"/photos/dog.jpg": (200, json.dumps("a dog"))})
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/photos/dog.jpg") == ("a dog",)
    finally:
        server.shutdown()


def test_missing_asset_returns_empty_string(monkeypatch):
    server = _start_server({})
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/photos/missing.jpg") == ("",)
    finally:
        server.shutdown()


def test_no_description_returns_empty_string(monkeypatch):
    server = _start_server(
        {"/photos/blank.jpg": (200, json.dumps({"description": None}))}
    )
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/photos/blank.jpg") == ("",)
    finally:
        server.shutdown()


def test_server_error_raises(monkeypatch):
    server = _start_server({"/photos/boom.jpg": (500, "boom")})
    try:
        get = _run_node(monkeypatch.setenv, server)
        try:
            get("/photos/boom.jpg")
        except RuntimeError as exc:
            assert "500" in str(exc)
        else:
            raise AssertionError("expected RuntimeError for HTTP 500")
    finally:
        server.shutdown()


def test_unreachable_raises(monkeypatch):
    # Point at a port nothing is listening on.
    monkeypatch.setenv("PHOTOHANDLER_URL", "http://127.0.0.1:1")
    try:
        PhotoHandlerDescription().get_description("/photos/x.jpg")
    except RuntimeError as exc:
        assert "PhotoHandler" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when unreachable")


# --- minimal stand-in so the suite also runs without pytest installed ------

class _MonkeyPatch:
    def __init__(self):
        self._saved = []

    def setenv(self, key, value):
        import os

        self._saved.append((key, os.environ.get(key)))
        os.environ[key] = value

    def undo(self):
        import os

        for key, value in reversed(self._saved):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._saved = []


def _main():
    tests = [
        test_returns_description_from_object,
        test_returns_description_from_bare_string,
        test_missing_asset_returns_empty_string,
        test_no_description_returns_empty_string,
        test_server_error_raises,
        test_unreachable_raises,
    ]
    failures = 0
    for test in tests:
        mp = _MonkeyPatch()
        try:
            test(mp)
            print("PASS", test.__name__)
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print("FAIL", test.__name__, "->", exc)
        finally:
            mp.undo()
    if failures:
        raise SystemExit("{} test(s) failed".format(failures))
    print("All tests passed.")


if __name__ == "__main__":
    _main()
