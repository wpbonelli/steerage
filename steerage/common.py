"""Configuration and shared helpers.

Settings come from environment variables:

- STEERAGE_DATA: output directory, default `./data`.
- STEERAGE_USER: GitHub login whose PRs to fetch, default the `gh` user.
- STEERAGE_FIRST_YEAR: first year to fetch, default the year the account was created.
- STEERAGE_SINCE: date (YYYY-MM-DD) agent-assisted work began. PRs before it
  are the pre-agent era. Required by the steps that split by era.
- STEERAGE_ROOT: directory holding the projects whose transcripts to read, default `~/dev`.
- STEERAGE_SKIP: colon-separated project paths whose transcripts to skip.
"""

import json
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

DATA = Path(os.environ.get("STEERAGE_DATA", "data")).resolve()
ROOT = Path(os.environ.get("STEERAGE_ROOT", Path.home() / "dev")).expanduser().resolve()
SKIP = {Path(p).expanduser().resolve() for p in os.environ.get("STEERAGE_SKIP", "").split(":") if p}

# Messages that carry no revision signal.
NOISE = re.compile(
    r"^\s*(y|yes|yep|ok|okay|k|sure|go|go ahead|continue|proceed|do it|thanks?|thank you|"
    r"lgtm|great|perfect|nice|cool|sounds good|looks good)[.!]*\s*$",
    re.I,
)

# Agent markers: text carrying one was drafted by an agent.
AGENT_FOOTER = re.compile(r"\n*🤖?\s*Generated with \[Claude Code\].*", re.S)  # PR body footer, stripped
AGENT_BODY = re.compile(r"Generated with|Copilot coding agent")  # in a PR body
AGENT_TRAILER = "co-authored-by: claude"  # in a commit message, lowercased


@cache
def gh_user() -> dict:
    out = subprocess.run(["gh", "api", "user"], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def user() -> str:
    return os.environ.get("STEERAGE_USER") or gh_user()["login"]


def first_year() -> int:
    return int(os.environ.get("STEERAGE_FIRST_YEAR") or gh_user()["created_at"][:4])


@cache
def since() -> str:
    s = os.environ.get("STEERAGE_SINCE")
    if not s:
        sys.exit("set STEERAGE_SINCE to the date agent-assisted work began (YYYY-MM-DD)")
    return s


def clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n // 2] + "\n[...]\n" + text[-n // 2 :]


def write_jsonl(path: Path, rows) -> int:
    n = 0
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
            n += 1
    return n


def read_jsonl(path: Path):
    with open(path) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
