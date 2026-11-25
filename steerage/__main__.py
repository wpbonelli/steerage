"""Run pipeline steps: `steerage [step ...]`, all steps in order by default."""

import sys
from importlib import import_module

from . import common
from .common import DATA

STEPS = ["transcripts", "github", "digest", "themes", "pairs", "eras"]
MODULES = {"transcripts": "claude_code"}


def module(step):
    return import_module(f".{MODULES.get(step, step)}", __package__)


def usage():
    lines = [__doc__ + "\n", common.__doc__.split("\n\n", 1)[1], "Steps:\n"]
    for s in STEPS:
        doc = module(s).__doc__.strip()
        lines.append(f"{s}\n    " + doc.replace("\n", "\n    ") + "\n")
    return "\n".join(lines)


def main():
    steps = sys.argv[1:] or STEPS
    if {"-h", "--help"} & set(steps):
        print(usage())
        return
    if unknown := [s for s in steps if s not in STEPS]:
        sys.exit(f"unknown steps {unknown}, choose from {STEPS}, or see --help")
    DATA.mkdir(parents=True, exist_ok=True)
    for s in steps:
        print(f"== {s}", file=sys.stderr)
        module(s).main()


if __name__ == "__main__":
    main()
