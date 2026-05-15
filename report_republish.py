#!/usr/bin/env python3
"""Republie un rapport de run existant vers les canaux choisis.

Usage:
    python report_republish.py --run-id <id> --channels notion,slack,gdrive
"""
from __future__ import annotations
import argparse
import sys
import logging

import persistence

log = logging.getLogger("republish")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--channels", required=True, help="comma-separated: notion,slack,gdrive")
    args = ap.parse_args()

    channels = {c.strip() for c in args.channels.split(",") if c.strip()}
    valid = {"notion", "slack", "gdrive", "obsidian"}
    invalid = channels - valid
    if invalid:
        print(f"Unknown channels: {invalid}", file=sys.stderr)
        return 2

    run = persistence.fetch_llm_run(args.run_id)
    if not run:
        print(f"Run {args.run_id} not found", file=sys.stderr)
        return 2

    log.info("Republishing run %s to channels=%s", args.run_id, sorted(channels))

    # Charger les modules de publication uniquement si nécessaires (graceful si import échoue)
    errors: list[str] = []

    if "slack" in channels:
        try:
            import notifier  # type: ignore
            if hasattr(notifier, "republish_run"):
                notifier.republish_run(run)
            else:
                log.warning("notifier.republish_run absent — Slack republish skip (à implémenter)")
        except Exception as exc:
            errors.append(f"slack: {exc}")

    if "notion" in channels:
        try:
            import notion_reporter  # type: ignore
            if hasattr(notion_reporter, "republish_run"):
                notion_reporter.republish_run(run)
            else:
                log.warning("notion_reporter.republish_run absent — Notion republish skip")
        except Exception as exc:
            errors.append(f"notion: {exc}")

    if "gdrive" in channels:
        try:
            import gdrive_uploader  # type: ignore
            if hasattr(gdrive_uploader, "republish_run"):
                gdrive_uploader.republish_run(run)
            else:
                log.warning("gdrive_uploader.republish_run absent — GDrive republish skip")
        except Exception as exc:
            errors.append(f"gdrive: {exc}")

    if "obsidian" in channels:
        try:
            import obsidian_reporter  # type: ignore
            if hasattr(obsidian_reporter, "republish_run"):
                obsidian_reporter.republish_run(run)
            else:
                log.warning("obsidian_reporter.republish_run absent — Obsidian republish skip")
        except Exception as exc:
            errors.append(f"obsidian: {exc}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
