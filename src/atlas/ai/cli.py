"""Research CLI. It reads a prompt and prints a note. It does not trade."""

from __future__ import annotations

import argparse
import sys

from atlas.ai.gemini_provider import GeminiResearchProvider
from atlas.ai.policy import PolicyError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Draft one ATLAS research note with Gemini. This command cannot trade."
    )
    parser.add_argument("context", help="Market observations. Do not include secrets.")
    parser.add_argument("--workload", choices=("frequent", "deep"), default="frequent")
    args = parser.parse_args(argv)
    try:
        note = GeminiResearchProvider(workload=args.workload).analyze(args.context)
    except (PolicyError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(note.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
