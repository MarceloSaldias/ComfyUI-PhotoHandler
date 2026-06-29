"""Tests for the PhotoHandler Description nodes.

A lightweight local HTTP server stands in for PhotoHandler so the nodes can be
exercised end to end without any external dependencies. Run with::

    python test_photohandler_node.py

or under pytest::

    pytest test_photohandler_node.py
"""

import json
import os
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from photohandler_node import (
    PhotoHandlerDescription,
    PhotoHandlerDescriptionByImage,
    _sha256_file,
)


class _FakeHandler(BaseHTTPRequestHandler):
    # path-keyed and hash-keyed response specs for the running server. Each spec
    # is either (status, body) or a callable(query_params) -> (status, body).
    path_responses = {}
    hash_responses = {}

    def log_message(self, *args):  # silence the test server
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/api/assets/by-path/description":
            key = params.get("path", [""])[0]
            spec = self.path_responses.get(key)
            outside = json.dumps(
                {"error": "Access denied: '%s' is outside the library" % key}
            )
        elif parsed.path == "/api/assets/by-hash/description":
            key = params.get("hash", [""])[0]
            spec = self.hash_responses.get(key)
            # Mirror the by-hash endpoint: unknown hash is indexed-but-absent,
            # reported as a normal empty 200 (no ensure_readable gate).
            outside = json.dumps(
                {"path": "", "description": "", "asset_id": None, "descriptions": {}}
            )
        else:
            self.send_response(404)
            self.end_headers()
            return

        if spec is None:
            status, body = (200 if parsed.path.endswith("by-hash/description") else 500), outside
        elif callable(spec):
            status, body = spec(params)
        else:
            status, body = spec

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def _start_server(path_responses=None, hash_responses=None):
    _FakeHandler.path_responses = path_responses or {}
    _FakeHandler.hash_responses = hash_responses or {}
    server = HTTPServer(("127.0.0.1", 0), _FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _set_url(monkeypatch_env, server):
    host, port = server.server_address
    monkeypatch_env("PHOTOHANDLER_URL", "http://{}:{}".format(host, port))


def _ok(payload):
    return (200, json.dumps(payload))


# --------------------------------------------------------------------------
# Path-based node
# --------------------------------------------------------------------------

def test_path_returns_description_and_map(monkeypatch):
    server = _start_server(
        path_responses={
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
        _set_url(monkeypatch.setenv, server)
        desc, maps = PhotoHandlerDescription().get_description("/lib/cat.jpg")
        assert desc == "a cat"
        assert json.loads(maps) == {"Scene": "a cat", "Clothing": "none"}
    finally:
        server.shutdown()


def test_path_type_param_is_forwarded(monkeypatch):
    def respond(params):
        chosen = params.get("type", ["<none>"])[0]
        return _ok(
            {"path": "/lib/x.jpg", "description": "for-" + chosen, "asset_id": 2,
             "descriptions": {}}
        )

    server = _start_server(path_responses={"/lib/x.jpg": respond})
    try:
        _set_url(monkeypatch.setenv, server)
        node = PhotoHandlerDescription()
        assert node.get_description("/lib/x.jpg", "Clothing")[0] == "for-Clothing"
        assert node.get_description("/lib/x.jpg")[0] == "for-<none>"
    finally:
        server.shutdown()


def test_path_outside_library_returns_empty(monkeypatch):
    server = _start_server()  # no mapping -> 500 "outside the library"
    try:
        _set_url(monkeypatch.setenv, server)
        assert PhotoHandlerDescription().get_description("/elsewhere.jpg") == ("", "{}")
    finally:
        server.shutdown()


def test_path_unreadable_raises(monkeypatch):
    server = _start_server(
        path_responses={
            "/lib/gone.jpg": (
                500,
                json.dumps({"error": "Cannot access path '/lib/gone.jpg': No such file"}),
            )
        }
    )
    try:
        _set_url(monkeypatch.setenv, server)
        try:
            PhotoHandlerDescription().get_description("/lib/gone.jpg")
        except RuntimeError as exc:
            assert "Cannot access path" in str(exc)
        else:
            raise AssertionError("expected RuntimeError for unreadable path")
    finally:
        server.shutdown()


# --------------------------------------------------------------------------
# Image / SHA-based node
# --------------------------------------------------------------------------

def _temp_image(content=b"fake-jpeg-bytes"):
    fd, path = tempfile.mkstemp(suffix=".jpg")
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)
    return path


def test_image_lookup_by_hash(monkeypatch):
    path = _temp_image(b"distinct-bytes-A")
    sha = _sha256_file(path)
    server = _start_server(
        hash_responses={
            sha: _ok(
                {
                    "path": "/lib/orig.jpg",
                    "description": "matched by hash",
                    "asset_id": 7,
                    "descriptions": {"Scene": "matched by hash"},
                }
            )
        }
    )
    try:
        _set_url(monkeypatch.setenv, server)
        # folder_paths is absent outside ComfyUI, so `image` is used as a path.
        desc, maps = PhotoHandlerDescriptionByImage().get_description(path)
        assert desc == "matched by hash"
        assert json.loads(maps) == {"Scene": "matched by hash"}
    finally:
        server.shutdown()
        os.remove(path)


def test_image_type_param_is_forwarded(monkeypatch):
    path = _temp_image(b"distinct-bytes-B")
    sha = _sha256_file(path)

    def respond(params):
        chosen = params.get("type", ["<none>"])[0]
        return _ok(
            {"path": "/lib/o.jpg", "description": "for-" + chosen, "asset_id": 8,
             "descriptions": {}}
        )

    server = _start_server(hash_responses={sha: respond})
    try:
        _set_url(monkeypatch.setenv, server)
        node = PhotoHandlerDescriptionByImage()
        assert node.get_description(path, "Clothing")[0] == "for-Clothing"
    finally:
        server.shutdown()
        os.remove(path)


def test_image_unknown_hash_returns_empty(monkeypatch):
    path = _temp_image(b"never-seen-bytes")
    server = _start_server(hash_responses={})  # unknown hash -> empty 200
    try:
        _set_url(monkeypatch.setenv, server)
        assert PhotoHandlerDescriptionByImage().get_description(path) == ("", "{}")
    finally:
        server.shutdown()
        os.remove(path)


def test_image_missing_file_raises(monkeypatch):
    server = _start_server()
    try:
        _set_url(monkeypatch.setenv, server)
        try:
            PhotoHandlerDescriptionByImage().get_description("/no/such/file.jpg")
        except RuntimeError as exc:
            assert "Could not read image file" in str(exc)
        else:
            raise AssertionError("expected RuntimeError for missing file")
    finally:
        server.shutdown()


def test_is_changed_tracks_content(monkeypatch):
    path = _temp_image(b"content-1")
    try:
        first = PhotoHandlerDescriptionByImage.IS_CHANGED(path)
        with open(path, "wb") as handle:
            handle.write(b"content-2-different")
        second = PhotoHandlerDescriptionByImage.IS_CHANGED(path)
        assert first != second
    finally:
        os.remove(path)


# --------------------------------------------------------------------------
# Shared
# --------------------------------------------------------------------------

def test_unreachable_raises(monkeypatch):
    monkeypatch.setenv("PHOTOHANDLER_URL", "http://127.0.0.1:1")
    try:
        PhotoHandlerDescription().get_description("/lib/x.jpg")
    except RuntimeError as exc:
        assert "PhotoHandler" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when unreachable")


def test_bare_string_response(monkeypatch):
    server = _start_server(path_responses={"/lib/dog.jpg": _ok("a dog")})
    try:
        _set_url(monkeypatch.setenv, server)
        assert PhotoHandlerDescription().get_description("/lib/dog.jpg") == ("a dog", "{}")
    finally:
        server.shutdown()


# --- minimal stand-in so the suite also runs without pytest installed ------

class _MonkeyPatch:
    def __init__(self):
        self._saved = []

    def setenv(self, key, value):
        self._saved.append((key, os.environ.get(key)))
        os.environ[key] = value

    def undo(self):
        for key, value in reversed(self._saved):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._saved = []


def _main():
    tests = [
        test_path_returns_description_and_map,
        test_path_type_param_is_forwarded,
        test_path_outside_library_returns_empty,
        test_path_unreadable_raises,
        test_image_lookup_by_hash,
        test_image_type_param_is_forwarded,
        test_image_unknown_hash_returns_empty,
        test_image_missing_file_raises,
        test_is_changed_tracks_content,
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
