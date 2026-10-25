from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import FactoryConfig
from .pipeline import (
    default_run_dir,
    run_manual_selection,
    run_phase1,
    run_phase2,
    run_phase3,
    run_phase4,
)
from .preflight import run_preflight


def _add_production_options(command: argparse.ArgumentParser, *, config: bool = True) -> None:
    if config:
        command.add_argument("--config", required=True, type=Path)
    command.add_argument("--run-dir", type=Path)
    command.add_argument("--date")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--research-dir", type=Path)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="jaguartv-prematch")
    commands = root.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight", help="Validate static-poster routes without production writes")
    preflight.add_argument("--config", required=True, type=Path)
    preflight.add_argument("--dry-run", action="store_true")

    recommend = commands.add_parser("recommend", help="Collect and rank candidates; never generates posters")
    recommend.add_argument("--config", required=True, type=Path)
    recommend.add_argument("--run-dir", type=Path)
    recommend.add_argument("--date", default="tomorrow")
    recommend.add_argument("--fixtures-file", type=Path)

    select = commands.add_parser("select", help="Record the operator-approved fixtures before production")
    select.add_argument("--run-dir", required=True, type=Path)
    select.add_argument("--fixture-id", action="append", default=[])
    select.add_argument("--decisions", type=Path, help="JSON containing selected_fixture_ids and optional poster_styles")
    select.add_argument("--operator", default="")
    select.add_argument("--note", default="")

    produce = commands.add_parser("produce", help="Research, generate, compose, QA and deliver static PNG posters")
    _add_production_options(produce)

    for name, help_text in (
        ("phase2", "Debug the research gate after manual selection"),
        ("phase3", "Debug static poster generation after manual selection"),
        ("phase4", "Debug static poster delivery after generation"),
    ):
        command = commands.add_parser(name, help=help_text)
        _add_production_options(command)

    return root


def _decision_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Selection decisions must be a JSON object.")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "preflight":
            config = FactoryConfig.load(args.config)
            repository = Path(__file__).resolve().parents[2]
            report = run_preflight(config, repository)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if report["production_ready"]:
                return 0
            blocked = {item["name"] for item in report["checks"] if item["status"] not in {"ok", "configured"}}
            return 0 if args.dry_run and blocked <= {"image_primary", "image_fallback"} else 1

        if args.command == "recommend":
            config = FactoryConfig.load(args.config)
            run_dir = args.run_dir or default_run_dir(args.date)
            result = run_phase1(config, run_dir, args.fixtures_file, args.date)
        elif args.command == "select":
            decisions = _decision_payload(args.decisions) if args.decisions else {}
            fixture_ids = list(args.fixture_id) or list(decisions.get("selected_fixture_ids") or [])
            styles = decisions.get("poster_styles") or {}
            if not isinstance(styles, dict):
                raise ValueError("poster_styles must map fixture IDs to auto, fan_crowd or star_faceoff.")
            result = run_manual_selection(
                args.run_dir,
                fixture_ids,
                poster_styles={str(key): str(value) for key, value in styles.items()},
                operator=args.operator or str(decisions.get("operator") or ""),
                note=args.note or str(decisions.get("note") or ""),
            )
        else:
            config = FactoryConfig.load(args.config)
            run_dir = args.run_dir or default_run_dir(args.date)
            if args.command == "produce":
                result = {
                    "phase2": run_phase2(run_dir, dry_run=args.dry_run, research_dir=args.research_dir),
                    "phase3": run_phase3(config, run_dir, dry_run=args.dry_run),
                    "phase4": run_phase4(config, run_dir, dry_run=args.dry_run),
                }
            elif args.command == "phase2":
                result = run_phase2(run_dir, dry_run=args.dry_run, research_dir=args.research_dir)
            elif args.command == "phase3":
                result = run_phase3(config, run_dir, dry_run=args.dry_run)
            else:
                result = run_phase4(config, run_dir, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:  # noqa: BLE001 - keep automation output machine-readable.
        print(json.dumps({"ok": False, "blocked_command": args.command, "sanitized_error": str(error)[:800]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
