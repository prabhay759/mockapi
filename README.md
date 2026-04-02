# mockapi

> Spin up a fully functional mock HTTP server from a YAML or JSON spec in one line. Dynamic response rules, request logging, hot reload, and a CLI tool. Zero dependencies.

[![PyPI version](https://img.shields.io/pypi/v/mockapi.svg)](https://pypi.org/project/mockapi/)
[![Python](https://img.shields.io/pypi/pyversions/mockapi.svg)](https://pypi.org/project/mockapi/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Installation

```bash
pip install mockapi          # JSON specs only
pip install mockapi[yaml]    # adds YAML support
```

---

## Quick Start

```bash
# Start a mock server from a YAML spec
mockapi serve spec.yaml
```

```python
# Or use it in Python tests
from mockapi import MockAPI

with MockAPI("spec.yaml") as api:
    response = requests.get(api.url + "/users")
    assert response.json() == [{"id": 1, "name": "Alice"}]
```

---

## Spec Format

### YAML (`spec.yaml`)

```yaml
routes:
  - method: GET
    path: /users
    status: 200
    body:
      - id: 1
        name: Alice
      - id: 2
        name: Bob

  - method: GET
    path: /users/{id}
    status: 200
    body:
      id: 1
      name: Alice
    rules:
      - match:
          path_param:
            id: "999"
        then:
          status: 404
          body:
            error: User not found

  - method: POST
    path: /users
    status: 201
    body:
      id: 3
      name: Created

  - method: GET
    path: /slow
    body: {}
    delay: 1.5

  - method: GET
    path: /broken
    error: timeout
```

### JSON (`spec.json`)

```json
{
  "routes": [
    {"method": "GET", "path": "/ping", "status": 200, "body": {"ok": true}},
    {"method": "POST", "path": "/echo", "status": 201, "body": {"received": true}}
  ]
}
```

---

## CLI

```bash
# Basic usage
mockapi serve spec.yaml

# Custom port and host
mockapi serve spec.json --port 9000 --host 0.0.0.0

# Disable hot reload
mockapi serve spec.yaml --no-reload

# Quiet mode (no request logs)
mockapi serve spec.yaml --quiet
```

Output:
```
=======================================================
  mockapi — Mock API Server
  URL:      http://127.0.0.1:8888
  Spec:     spec.yaml
  Routes:   4
  Hot reload: ✅
=======================================================

  GET     /users                         → 200
  GET     /users/{id}                    → 200
  POST    /users                         → 201
  GET     /slow                          → 200  [delay 1.5s]
```

---

## Python API

### Context Manager (for tests)

```python
from mockapi import MockAPI

with MockAPI("spec.yaml", port=8080) as api:
    # api.url = "http://127.0.0.1:8080"
    res = requests.get(api.url + "/users")
    assert res.status_code == 200
```

### Programmatic Routes

```python
api = MockAPI(port=8888, verbose=False)
api.add_route("GET",  "/ping",       body={"ok": True})
api.add_route("POST", "/users",      status=201, body={"created": True})
api.add_route("GET",  "/slow",       body={}, delay=2.0)
api.add_route("GET",  "/fail",       error="timeout")
api.add_route("GET",  "/users/{id}", body={"id": 1})
api.start()
```

### Dynamic Rules

Conditional responses based on path params, query strings, or request body:

```python
api.add_route("GET", "/users/{id}", body={"id": 1, "name": "Alice"}, rules=[
    {
        "match": {"path_param": {"id": "999"}},
        "then": {"status": 404, "body": {"error": "Not found"}}
    },
    {
        "match": {"query": {"format": "minimal"}},
        "then": {"status": 200, "body": {"id": 1}}
    }
])
```

### Request History & Stats

```python
# All requests
history = api.history
# [{"method": "GET", "path": "/users", "status": 200, "duration_ms": 1.2, ...}]

# Requests for a specific path
api.history_for("/users")

# Summary stats
api.stats()
# {"total": 42, "by_status": {200: 38, 404: 4}, "by_method": {"GET": 40, "POST": 2}}

# Clear history
api.clear_history()
```

### Hot Reload

The spec file is watched for changes automatically. Edit `spec.yaml` while the server is running and routes update within 1 second — no restart needed.

---

## Error Simulation

| `error` value | Behaviour |
|---|---|
| `timeout` | Hangs for 30 seconds |
| `connection_reset` | Closes connection immediately |
| `empty` | Returns empty response body |

---

## API Reference

### `MockAPI`

| Method | Description |
|---|---|
| `__init__(spec, host, port, hot_reload, verbose)` | Create server |
| `add_route(method, path, status, body, ...)` | Add a route |
| `start()` | Start background server |
| `stop()` | Stop server |
| `reload()` | Manually reload spec from file |
| `history` | List of all recorded requests |
| `history_for(path)` | Requests for a specific path |
| `stats()` | Summary statistics |
| `clear_history()` | Clear request log |
| `url` | Base URL string |

---

## Running Tests

```bash
pip install pytest pyyaml
pytest tests/ -v
```

---

## License

MIT © prabhay759
