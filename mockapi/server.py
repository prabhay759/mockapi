"""
mockapi.server
--------------
HTTP server that serves mock responses from a spec.
Supports hot reload, request logging, and dynamic rules.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .spec import Route, load_spec, spec_from_dict

logger = logging.getLogger("mockapi")


class RequestLog:
    """Thread-safe request history store."""

    def __init__(self, max_size: int = 1000):
        self._log: List[dict] = []
        self._lock = threading.Lock()
        self.max_size = max_size

    def record(self, entry: dict):
        with self._lock:
            self._log.append(entry)
            if len(self._log) > self.max_size:
                self._log.pop(0)

    def all(self) -> List[dict]:
        with self._lock:
            return list(self._log)

    def for_path(self, path: str) -> List[dict]:
        with self._lock:
            return [r for r in self._log if r.get("path") == path]

    def clear(self):
        with self._lock:
            self._log.clear()

    def summary(self) -> dict:
        with self._lock:
            total = len(self._log)
            by_status: Dict[int, int] = {}
            by_method: Dict[str, int] = {}
            for r in self._log:
                s = r.get("status", 0)
                m = r.get("method", "?")
                by_status[s] = by_status.get(s, 0) + 1
                by_method[m] = by_method.get(m, 0) + 1
        return {"total": total, "by_status": by_status, "by_method": by_method}


class MockRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler that serves mock responses."""

    # Set by MockServer before starting
    routes: List[Route] = []
    request_log: RequestLog = None
    verbose: bool = True

    def log_message(self, format, *args):
        if self.verbose:
            logger.info(f"  {self.address_string()} - {format % args}")

    def _parse_request(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length", 0))
        body_raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(body_raw) if body_raw else None
        except Exception:
            body = body_raw.decode(errors="replace")
        return path, query, body

    def _find_route(self, method: str, path: str) -> tuple:
        """Return (route, path_params) or (None, {})."""
        for route in self.routes:
            if route.method not in (method, "*"):
                continue
            params = route.match_path(path)
            if params is not None:
                return route, params
        return None, {}

    def _apply_rules(self, route: Route, path_params: dict,
                     query: dict, body: Any) -> Optional[dict]:
        """Check conditional rules and return override dict if matched."""
        for rule in route.rules:
            match = rule.get("match", {})
            matched = True

            if "path_param" in match:
                for k, v in match["path_param"].items():
                    if str(path_params.get(k)) != str(v):
                        matched = False; break

            if matched and "query" in match:
                for k, v in match["query"].items():
                    if query.get(k, [None])[0] != str(v):
                        matched = False; break

            if matched and "body" in match and isinstance(body, dict):
                for k, v in match["body"].items():
                    if str(body.get(k)) != str(v):
                        matched = False; break

            if matched:
                return rule.get("then", {})
        return None

    def _send_response(self, status: int, body: Any, headers: dict, delay: float):
        if delay > 0:
            time.sleep(delay)

        self.send_response(status)

        if isinstance(body, (dict, list)):
            content = json.dumps(body, indent=2).encode()
            self.send_header("Content-Type", "application/json")
        elif body is None:
            content = b""
            self.send_header("Content-Type", "application/json")
        else:
            content = str(body).encode()
            self.send_header("Content-Type", "text/plain")

        self.send_header("Content-Length", len(content))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(content)

    def _handle(self):
        method = self.command
        path, query, body = self._parse_request()
        started = datetime.now()

        route, path_params = self._find_route(method, path)

        if route is None:
            self._send_response(404, {"error": f"No mock route for {method} {path}"}, {}, 0)
            self._log(method, path, 404, started, None)
            return

        # Simulate errors
        if route.error == "timeout":
            time.sleep(30)
            return
        elif route.error == "connection_reset":
            self.connection.close()
            return
        elif route.error == "empty":
            self.wfile.write(b"")
            return

        # Apply dynamic rules
        override = self._apply_rules(route, path_params, query, body)
        status = override.get("status", route.status) if override else route.status
        resp_body = override.get("body", route.body) if override else route.body
        headers = dict(route.headers)

        self._send_response(status, resp_body, headers, route.delay)
        self._log(method, path, status, started, body)

    def _log(self, method, path, status, started, req_body):
        entry = {
            "method": method,
            "path": path,
            "status": status,
            "timestamp": started.isoformat(),
            "duration_ms": round((datetime.now() - started).total_seconds() * 1000, 2),
            "request_body": req_body,
        }
        if self.request_log:
            self.request_log.record(entry)

    def do_GET(self):    self._handle()
    def do_POST(self):   self._handle()
    def do_PUT(self):    self._handle()
    def do_DELETE(self): self._handle()
    def do_PATCH(self):  self._handle()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()


class MockServer:
    """
    Low-level mock HTTP server. Use MockAPI for a friendlier interface.
    """

    def __init__(self, routes: List[Route], host: str = "127.0.0.1",
                 port: int = 8888, verbose: bool = True):
        self.routes = routes
        self.host = host
        self.port = port
        self.verbose = verbose
        self.request_log = RequestLog()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        handler = type("Handler", (MockRequestHandler,), {
            "routes": self.routes,
            "request_log": self.request_log,
            "verbose": self.verbose,
        })
        self._server = HTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="mockapi"
        )
        self._thread.start()
        logger.info("[mockapi] Server running at http://%s:%d", self.host, self.port)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._thread.join(timeout=3)

    def reload(self, routes: List[Route]):
        self.routes = routes
        # Update handler class routes live
        if self._server:
            self._server.RequestHandlerClass.routes = routes

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class MockAPI:
    """
    High-level mock API server.

    Parameters
    ----------
    spec : str | dict, optional
        Path to a YAML/JSON spec file, or a dict.
    host : str
        Bind address. Default: "127.0.0.1".
    port : int
        Port to listen on. Default: 8888.
    hot_reload : bool
        Watch spec file for changes and reload automatically. Default: True.
    verbose : bool
        Log requests to stdout. Default: True.

    Examples
    --------
    >>> api = MockAPI("spec.yaml", port=8080)
    >>> api.start()
    >>> # ... run tests ...
    >>> api.stop()

    >>> # As a context manager:
    >>> with MockAPI("spec.yaml") as api:
    ...     requests.get(api.url + "/users")

    >>> # Programmatic:
    >>> api = MockAPI()
    >>> api.add_route("GET", "/ping", body={"ok": True})
    >>> api.start()
    """

    def __init__(
        self,
        spec: Optional[Any] = None,
        host: str = "127.0.0.1",
        port: int = 8888,
        hot_reload: bool = True,
        verbose: bool = True,
    ):
        self._spec_path: Optional[str] = None
        self._routes: List[Route] = []
        self._host = host
        self._port = port
        self._hot_reload = hot_reload
        self._verbose = verbose
        self._server: Optional[MockServer] = None
        self._reload_thread: Optional[threading.Thread] = None
        self._stop_reload = threading.Event()
        self._spec_mtime: float = 0

        if isinstance(spec, str):
            self._spec_path = spec
            self._routes = load_spec(spec)
            self._spec_mtime = os.path.getmtime(spec)
        elif isinstance(spec, dict):
            self._routes = spec_from_dict(spec)

    def add_route(
        self,
        method: str,
        path: str,
        status: int = 200,
        body: Any = None,
        headers: Optional[Dict] = None,
        delay: float = 0.0,
        error: Optional[str] = None,
        rules: Optional[List[dict]] = None,
    ) -> "MockAPI":
        """Add a route programmatically."""
        self._routes.append(Route(
            method=method, path=path, status=status, body=body,
            headers=headers or {}, delay=delay, error=error, rules=rules or [],
        ))
        if self._server:
            self._server.reload(self._routes)
        return self

    def start(self) -> "MockAPI":
        """Start the mock server."""
        self._server = MockServer(
            self._routes, self._host, self._port, self._verbose
        )
        self._server.start()
        if self._hot_reload and self._spec_path:
            self._start_hot_reload()
        return self

    def stop(self):
        """Stop the mock server."""
        self._stop_reload.set()
        if self._server:
            self._server.stop()

    def reload(self) -> "MockAPI":
        """Manually reload spec from file."""
        if self._spec_path:
            self._routes = load_spec(self._spec_path)
            if self._server:
                self._server.reload(self._routes)
            logger.info("[mockapi] Spec reloaded from %s", self._spec_path)
        return self

    def _start_hot_reload(self):
        def watch():
            while not self._stop_reload.is_set():
                try:
                    mtime = os.path.getmtime(self._spec_path)
                    if mtime != self._spec_mtime:
                        self._spec_mtime = mtime
                        self.reload()
                except Exception:
                    pass
                self._stop_reload.wait(1.0)

        self._reload_thread = threading.Thread(
            target=watch, daemon=True, name="mockapi-reload"
        )
        self._reload_thread.start()

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def history(self) -> List[dict]:
        """Return all recorded requests."""
        if self._server:
            return self._server.request_log.all()
        return []

    def history_for(self, path: str) -> List[dict]:
        """Return recorded requests for a specific path."""
        if self._server:
            return self._server.request_log.for_path(path)
        return []

    def clear_history(self):
        """Clear the request log."""
        if self._server:
            self._server.request_log.clear()

    def stats(self) -> dict:
        """Return request statistics."""
        if self._server:
            return self._server.request_log.summary()
        return {}

    def __enter__(self) -> "MockAPI":
        return self.start()

    def __exit__(self, *args):
        self.stop()

    def __repr__(self):
        return f"<MockAPI url={self.url} routes={len(self._routes)}>"
