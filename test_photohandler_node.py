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
    # Map of image path -> callable(query_params) -> (status, body) used by the
    # running server.
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
            # Mirror PhotoHandler: a path outside the library is a 500, not a 404.
            status, body = 500, json.dumps(
                {"error": "Access denied: '%s' is outside the library" % path}
            )
        elif callable(spec):
            status, body = spec(params)
        else:
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


def _ok(payload):
    return (200, json.dumps(payload))


def test_returns_description_and_map_from_object(monkeypatch):
    server = _start_server(
        {
            "/lib/cat.jpg": _ok(
                {
                    "path": "/lib/cat.jpg",
                    "description": "a cat",
                    "asset_id": 1,
                    "descriptions": {"Scene": "a cat", "Clothing": "none"},
                }
            )
        }
    )
    try:
        get = _run_node(monkeypatch.setenv, server)
        desc, maps = get("/lib/cat.jpg")
        assert desc == "a cat"
        assert json.loads(maps) == {"Scene": "a cat", "Clothing": "none"}
    finally:
        server.shutdown()


def test_type_param_is_forwarded(monkeypatch):
    def respond(params):
        # The selected description echoes whichever type was requested.
        chosen = params.get("type", ["<none>"])[0]
        return _ok(
            {
                "path": "/lib/x.jpg",
                "description": "for-" + chosen,
                "asset_id": 2,
                "descriptions": {"Clothing": "for-Clothing"},
            }
        )

    server = _start_server({"/lib/x.jpg": respond})
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/lib/x.jpg", "Clothing")[0] == "for-Clothing"
        # No type -> param absent on the server side.
        assert get("/lib/x.jpg")[0] == "for-<none>"
    finally:
        server.shutdown()


def test_indexed_but_no_description_returns_empty(monkeypatch):
    server = _start_server(
        {
            "/lib/blank.jpg": _ok(
                {
                    "path": "/lib/blank.jpg",
                    "description": "",
                    "asset_id": 3,
                    "descriptions": {},
                }
            )
        }
    )
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/lib/blank.jpg") == ("", "{}")
    finally:
        server.shutdown()


def test_outside_library_returns_empty(monkeypatch):
    # No mapping -> fake server replies 500 "outside the library".
    server = _start_server({})
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/somewhere/else.jpg") == ("", "{}")
    finally:
        server.shutdown()


def test_no_library_open_returns_empty(monkeypatch):
    server = _start_server(
        {"/lib/y.jpg": (500, json.dumps({"error": "No library is open"}))}
    )
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/lib/y.jpg") == ("", "{}")
    finally:
        server.shutdown()


def test_unreadable_path_raises(monkeypatch):
    server = _start_server(
        {
            "/lib/gone.jpg": (
                500,
                json.dumps(
                    {"error": "Cannot access path '/lib/gone.jpg': No such file"}
                ),
            )
        }
    )
    try:
        get = _run_node(monkeypatch.setenv, server)
        try:
            get("/lib/gone.jpg")
        except RuntimeError as exc:
            assert "Cannot access path" in str(exc)
        else:
            raise AssertionError("expected RuntimeError for unreadable path")
    finally:
        server.shutdown()


def test_unreachable_raises(monkeypatch):
    # Point at a port nothing is listening on.
    monkeypatch.setenv("PHOTOHANDLER_URL", "http://127.0.0.1:1")
    try:
        PhotoHandlerDescription().get_description("/lib/x.jpg")
    except RuntimeError as exc:
        assert "PhotoHandler" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when unreachable")


def test_bare_string_response(monkeypatch):
    server = _start_server({"/lib/dog.jpg": _ok("a dog")})
    try:
        get = _run_node(monkeypatch.setenv, server)
        assert get("/lib/dog.jpg") == ("a dog", "{}")
    finally:
        server.shutdown()


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
        test_returns_description_and_map_from_object,
        test_type_param_is_forwarded,
        test_indexed_but_no_description_returns_empty,
        test_outside_library_returns_empty,
        test_no_library_open_returns_empty,
        test_unreadable_path_raises,
        test_unreachable_raises,
        test_bare_string_response,
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
