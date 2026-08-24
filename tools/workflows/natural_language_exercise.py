"""Coordinate the single-call TimeCopilot natural-language exercise for P1-08."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from . import natural_language_provider as provider
from . import natural_language_publication as publication


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--live", action="store_true")
    actions.add_argument("--validate-publication", action="store_true")
    actions.add_argument("--update-roadmap", action="store_true")
    actions.add_argument("--check-roadmap", action="store_true")
    parser.add_argument("--publish", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.repo_root.resolve()
    try:
        if arguments.live:
            if os.environ.get(publication.RUNTIME_PREPARED_ENV) != "1":
                return provider.run_live_child(root, publish=arguments.publish)
            record = provider.run_live_exercise(root)
            if arguments.publish:
                publication.publish_bundle(record, root)
            return 0 if record["classification"] == "pass" else 1
        if arguments.publish:
            raise publication.PublicationError("--publish is valid only with --live")
        if arguments.validate_publication:
            publication.validate_publication(root)
        elif arguments.update_roadmap:
            publication.update_roadmap(root)
        elif arguments.check_roadmap and not publication.check_roadmap(root):
            raise publication.PublicationError(
                "P1-08 roadmap is inconsistent with validated evidence"
            )
    except (publication.NaturalLanguageError, OSError) as exc:
        print(f"natural-language: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
