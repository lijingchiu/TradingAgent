"""Runtime entry points used locally and by GitHub Actions."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import time

from .dashboard import build_snapshot
from .market import fetch_market
from .paper import tick


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("paper-tick", "dashboard", "serve", "run"))
    parser.add_argument("--state-dir", type=Path, default=Path("state"))
    parser.add_argument("--web-dir", type=Path, default=Path("web"))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state, web = args.state_dir.resolve(), args.web_dir.resolve()
    if args.command == "serve":
        handler = partial(SimpleHTTPRequestHandler, directory=str(web))
        print(f"Local monitoring server bound to 127.0.0.1:{args.port}", flush=True)
        ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
        return 0
    if args.command == "run" and args.interval < 300:
        parser.error("The polling interval must be at least 300 seconds")
    while True:
        failed = False
        if args.command in ("paper-tick", "run"):
            try:
                tick(state, root / "artifacts/selected_strategy.json", fetch_market)
            except Exception as error:
                print(type(error).__name__ + ": " + str(error), file=sys.stderr)
                failed = True
        snapshot = build_snapshot(root, state, web)
        print(json.dumps({"status": snapshot["status"], "equity": snapshot["account"]["equity"],
                          "paper_approved": snapshot["validation"]["passed"]}, ensure_ascii=False), flush=True)
        if args.command != "run":
            return 2 if failed else 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
