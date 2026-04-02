"""
mockapi.spec
------------
Load and parse mock API specs from YAML or JSON files.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class Route:
    """Represents a single mock API route."""
    method: str                          # GET, POST, PUT, DELETE, PATCH, *
    path: str                            # /users, /users/{id}
    status: int = 200                    # HTTP status code
    body: Any = None                     # Response body
    headers: Dict[str, str] = field(default_factory=dict)
    delay: float = 0.0                   # Simulated latency in seconds
    error: Optional[str] = None          # Force an error type
    description: str = ""
    # Conditional rules: list of {match: {body/query/header key: value}, then: {status, body}}
    rules: List[dict] = field(default_factory=list)

    def __post_init__(self):
        self.method = self.method.upper()
        if not self.path.startswith("/"):
            self.path = "/" + self.path

    def path_regex(self) -> re.Pattern:
        """Convert /users/{id} to a regex pattern."""
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", self.path)
        return re.compile(f"^{pattern}$")

    def match_path(self, path: str) -> Optional[Dict[str, str]]:
        """Return path params dict if path matches, else None."""
        m = self.path_regex().match(path)
        if m:
            return m.groupdict()
        return None


def load_spec(path: str) -> List[Route]:
    """
    Load a mock API spec from a YAML or JSON file.

    Returns a list of Route objects.

    YAML example:
    -------------
    routes:
      - method: GET
        path: /users
        status: 200
        body:
          - id: 1
            name: Alice
        delay: 0.1

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
              body: {error: "User not found"}

      - method: POST
        path: /users
        status: 201
        body: {id: 2, name: Created}

      - method: GET
        path: /error
        error: timeout
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML required: pip install pyyaml")
        with open(path) as f:
            data = yaml.safe_load(f)
    elif ext == ".json":
        with open(path) as f:
            data = json.load(f)
    else:
        raise ValueError(f"Unsupported spec format: {ext}. Use .yaml or .json")

    routes = []
    for r in data.get("routes", []):
        route = Route(
            method=r.get("method", "GET"),
            path=r.get("path", "/"),
            status=int(r.get("status", 200)),
            body=r.get("body"),
            headers=r.get("headers", {}),
            delay=float(r.get("delay", 0.0)),
            error=r.get("error"),
            description=r.get("description", ""),
            rules=r.get("rules", []),
        )
        routes.append(route)
    return routes


def spec_from_dict(data: Dict) -> List[Route]:
    """Create routes from a plain dict (for programmatic use)."""
    routes = []
    for r in data.get("routes", []):
        routes.append(Route(
            method=r.get("method", "GET"),
            path=r.get("path", "/"),
            status=int(r.get("status", 200)),
            body=r.get("body"),
            headers=r.get("headers", {}),
            delay=float(r.get("delay", 0.0)),
            error=r.get("error"),
            description=r.get("description", ""),
            rules=r.get("rules", []),
        ))
    return routes
