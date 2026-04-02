"""
mockapi CLI
-----------
Usage:
    mockapi serve spec.yaml
    mockapi serve spec.json --port 9000 --host 0.0.0.0
    mockapi serve spec.yaml --no-reload --quiet
"""

import argparse
import json
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main():
    parser = argparse.ArgumentParser(
        prog="mockapi",
        description="Serve a mock HTTP API from a YAML or JSON spec.",
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the mock server")
    serve.add_argument("spec", help="Path to spec file (.yaml or .json)")
    serve.add_argument("--port", "-p", type=int, default=8888, help="Port (default: 8888)")
    serve.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    serve.add_argument("--no-reload", action="store_true", help="Disable hot reload")
    serve.add_argument("--quiet", "-q", action="store_true", help="Suppress request logs")

    args = parser.parse_args()

    if args.command == "serve":
        _serve(args)
    else:
        parser.print_help()


def _serve(args):
    from .server import MockAPI
    from .spec import load_spec

    try:
        routes = load_spec(args.spec)
    except FileNotFoundError:
        print(f"  ❌ Spec file not found: {args.spec}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ Error loading spec: {e}", file=sys.stderr)
        sys.exit(1)

    api = MockAPI(
        spec=args.spec,
        host=args.host,
        port=args.port,
        hot_reload=not args.no_reload,
        verbose=not args.quiet,
    )

    print(f"\n{'='*55}")
    print(f"  mockapi — Mock API Server")
    print(f"  URL:      http://{args.host}:{args.port}")
    print(f"  Spec:     {args.spec}")
    print(f"  Routes:   {len(routes)}")
    print(f"  Hot reload: {'✅' if not args.no_reload else '❌'}")
    print(f"{'='*55}\n")

    for r in routes:
        desc = f"  ({r.description})" if r.description else ""
        delay = f"  [delay {r.delay}s]" if r.delay else ""
        error = f"  [error: {r.error}]" if r.error else ""
        print(f"  {r.method:<7} {r.path:<30} → {r.status}{delay}{error}{desc}")

    print(f"\n  Press Ctrl+C to stop.\n")

    api.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n\n  📊 Session stats:")
        stats = api.stats()
        print(f"     Total requests: {stats.get('total', 0)}")
        if stats.get('by_status'):
            for status, count in sorted(stats['by_status'].items()):
                print(f"     {status}: {count} requests")
        api.stop()
        print("  Stopped.\n")


if __name__ == "__main__":
    main()
