"""
mockapi — Spin up a mock HTTP server from a YAML/JSON spec.
Dynamic rules, request logging, hot reload, and a CLI tool.
"""

from .server import MockAPI, MockServer
from .spec import load_spec, Route

__all__ = ["MockAPI", "MockServer", "load_spec", "Route"]
__version__ = "1.0.0"
__author__ = "prabhay759"
