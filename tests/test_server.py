"""
Tests for mockapi.
Run with: pytest tests/ -v
"""

import json
import time
import threading
from pathlib import Path
from urllib import request, error as urllib_error

import pytest

from mockapi import MockAPI, Route
from mockapi.spec import load_spec, spec_from_dict


# ── Helpers ───────────────────────────────────────────────────────────────────

def get(url, timeout=3):
    with request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read())

def post(url, data, timeout=3):
    body = json.dumps(data).encode()
    req = request.Request(url, data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())

def find_free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── spec loading ──────────────────────────────────────────────────────────────

class TestSpecLoading:
    def test_from_dict(self):
        routes = spec_from_dict({"routes": [
            {"method": "GET", "path": "/ping", "status": 200, "body": {"ok": True}}
        ]})
        assert len(routes) == 1
        assert routes[0].method == "GET"
        assert routes[0].path == "/ping"
        assert routes[0].status == 200

    def test_from_json_file(self, tmp_path):
        f = tmp_path / "spec.json"
        f.write_text(json.dumps({"routes": [
            {"method": "GET", "path": "/test", "body": "ok"}
        ]}))
        routes = load_spec(str(f))
        assert len(routes) == 1
        assert routes[0].path == "/test"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_spec("/nonexistent/spec.yaml")

    def test_default_status_200(self):
        routes = spec_from_dict({"routes": [{"method": "GET", "path": "/x"}]})
        assert routes[0].status == 200


# ── Route ─────────────────────────────────────────────────────────────────────

class TestRoute:
    def test_path_param_match(self):
        r = Route("GET", "/users/{id}")
        params = r.match_path("/users/42")
        assert params == {"id": "42"}

    def test_no_match(self):
        r = Route("GET", "/users/{id}")
        assert r.match_path("/posts/1") is None

    def test_exact_match(self):
        r = Route("GET", "/ping")
        assert r.match_path("/ping") == {}
        assert r.match_path("/pong") is None

    def test_method_uppercase(self):
        r = Route("get", "/test")
        assert r.method == "GET"

    def test_path_prefixed(self):
        r = Route("GET", "no-slash")
        assert r.path == "/no-slash"


# ── MockAPI ───────────────────────────────────────────────────────────────────

class TestMockAPI:
    def test_basic_get(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/ping", body={"ok": True})
            status, body = get(f"http://127.0.0.1:{port}/ping")
        assert status == 200
        assert body == {"ok": True}

    def test_custom_status(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/not-found", status=404, body={"error": "nope"})
            status, body = get(f"http://127.0.0.1:{port}/not-found")
        assert status == 404

    def test_404_for_unknown_route(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/known", body={})
            with pytest.raises(urllib_error.HTTPError) as exc:
                get(f"http://127.0.0.1:{port}/unknown")
            assert exc.value.code == 404

    def test_path_params(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/users/{id}", body={"id": 1, "name": "Alice"})
            status, body = get(f"http://127.0.0.1:{port}/users/42")
        assert status == 200
        assert body["name"] == "Alice"

    def test_delay(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/slow", body={}, delay=0.2)
            start = time.monotonic()
            get(f"http://127.0.0.1:{port}/slow")
            elapsed = time.monotonic() - start
        assert elapsed >= 0.15

    def test_post_route(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("POST", "/users", status=201, body={"created": True})
            status, body = post(f"http://127.0.0.1:{port}/users", {"name": "Bob"})
        assert status == 201
        assert body["created"] is True

    def test_request_history(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/ping", body={})
            get(f"http://127.0.0.1:{port}/ping")
            get(f"http://127.0.0.1:{port}/ping")
            history = api.history
        assert len(history) == 2
        assert history[0]["path"] == "/ping"

    def test_stats(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/a", body={})
            api.add_route("GET", "/b", status=404, body={})
            get(f"http://127.0.0.1:{port}/a")
            get(f"http://127.0.0.1:{port}/a")
            try:
                get(f"http://127.0.0.1:{port}/b")
            except urllib_error.HTTPError:
                pass
            stats = api.stats()
        assert stats["total"] == 3
        assert stats["by_status"][200] == 2
        assert stats["by_status"][404] == 1

    def test_clear_history(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/x", body={})
            get(f"http://127.0.0.1:{port}/x")
            api.clear_history()
            assert api.history == []

    def test_wildcard_method(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("*", "/any", body={"ok": True})
            status, _ = get(f"http://127.0.0.1:{port}/any")
        assert status == 200

    def test_context_manager(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/cm", body={"ctx": True})
            status, body = get(f"http://127.0.0.1:{port}/cm")
        assert body["ctx"] is True

    def test_add_route_while_running(self):
        port = find_free_port()
        with MockAPI(port=port, verbose=False) as api:
            api.add_route("GET", "/first", body={"n": 1})
            get(f"http://127.0.0.1:{port}/first")
            api.add_route("GET", "/second", body={"n": 2})
            status, body = get(f"http://127.0.0.1:{port}/second")
        assert body["n"] == 2

    def test_hot_reload_from_file(self, tmp_path):
        port = find_free_port()
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps({"routes": [
            {"method": "GET", "path": "/v", "body": {"v": 1}}
        ]}))
        with MockAPI(str(spec_file), port=port, hot_reload=True, verbose=False) as api:
            _, body = get(f"http://127.0.0.1:{port}/v")
            assert body["v"] == 1
            # Update spec
            spec_file.write_text(json.dumps({"routes": [
                {"method": "GET", "path": "/v", "body": {"v": 2}}
            ]}))
            time.sleep(1.5)  # Wait for hot reload
            _, body = get(f"http://127.0.0.1:{port}/v")
        assert body["v"] == 2

    def test_url_property(self):
        port = find_free_port()
        api = MockAPI(port=port, verbose=False)
        assert api.url == f"http://127.0.0.1:{port}"
