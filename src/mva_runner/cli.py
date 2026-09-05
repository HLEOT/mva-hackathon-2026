"""Public CLI: technical state only; private evidence stays in files."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys

from mva_track1.common import PROJECT_ROOT, Track1Error, load_jsonish
from .storage import EXECUTION, establish_baseline, require_space, snapshot
from . import supervisor


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mva")
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--offline", action="store_true", help="Do not contact authentication/publication endpoints; network checks remain unverified")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    for name in ("run", "_supervise"):
        p = sub.add_parser(name)
        p.add_argument("--tracks", choices=["both", "track1"], default="both",
                       help="both: full local pipeline; track1: scientific-only subset without two-track packaging")
        p.add_argument("--resume", action="store_true")
        p.add_argument("--stages", nargs="*", default=[])
        p.add_argument("--foreground", action="store_true")
    sub.add_parser("package")
    sub.add_parser("stop")
    args = parser.parse_args(argv)
    cfg = load_jsonish(EXECUTION)
    if args.command == "preflight":
        establish_baseline()
        from .preflight import collect
        report = collect(cfg, offline=args.offline)
        print(json.dumps(report, indent=2))
        return 0 if report["base_prerequisites_verified"] else 2
    elif args.command == "status":
        state = supervisor.read_state()
        report = {"status": state.get("status", "not_started"),
                  "supervisor_live": supervisor.is_live(state.get("supervisor")),
                  "tracks": state.get("tracks"),
                  "selected_stages": state.get("selected_stages", []),
                  "completion_scope": "selected local stages; code publication is verified separately",
                  "heartbeat": state.get("heartbeat"),
                  "stages": {n: {"child_live": supervisor.is_live(r.get("child")),
                      "child_paused": supervisor.is_paused(r.get("child")), **{k:v for k,v in r.items() if k in
                      {"status", "started_at", "completed_at", "attempts", "error_category", "space_request", "log"}}
                      } for n,r in state.get("stages", {}).items()}, "storage": snapshot()}
        report["paused_stages"] = [name for name, record in report["stages"].items()
                                   if record.get("status") == "running" and record["child_paused"]]
        print(json.dumps(report, indent=2))
    elif args.command == "stop":
        print(supervisor.request_stop())
    elif args.command == "package":
        return supervisor.run("both", ("package",))
    elif args.command == "_supervise" or args.foreground:
        return supervisor.run(args.tracks, tuple(args.stages))
    else:
        establish_baseline()
        session = cfg["supervisor"]["session"]
        if supervisor.is_live(supervisor.read_state().get("supervisor")):
            raise Track1Error("A live supervisor already exists; use status")
        cmd = [str(PROJECT_ROOT / "mva"), "_supervise", "--tracks", args.tracks, "--resume"]
        if args.stages:
            cmd += ["--stages", *args.stages]
        subprocess.run(["tmux", "new-session", "-d", "-s", session, shlex.join(cmd)], check=True)
        print(f"Started persistent session {session}; use ./mva status --json.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Track1Error, OSError, subprocess.CalledProcessError) as exc:
        print(f"Workflow error: {type(exc).__name__}. Check local stage logs.", file=sys.stderr)
        raise SystemExit(2)
