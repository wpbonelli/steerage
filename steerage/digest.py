"""Merge extracted events and PR data into readable digests for synthesis.

Outputs (data/):
  feedback_revisions.md  user turns that look like revisions of prior work
  feedback_other.md      remaining follow-up turns (skim for missed signal)
  pr_body_diffs.md       original vs final PR description
  pr_revisions.md        revision commits after the first in each PR
  stats.md               keyword counts over all follow-up turns
  compact_*.txt          one line per turn, for fast reading
"""

import difflib
import json
import re
from collections import Counter, defaultdict

from .common import DATA, clip, read_jsonl, since, user

# Phrases suggesting the user is revising/correcting prior output.
REVISION = re.compile(
    r"\b(terse|tersen|concise|shorter|shorten|brief|verbose|wordy|trim|tighten|condense|cut|"
    r"too (long|much|many|verbose)|less|fewer|simplif|simpler|overkill|over-?engineer|"
    r"don'?t|do not|didn'?t|never|stop|instead|rather|actually|wrong|incorrect|not what|"
    r"why (did|do|are|would)|remove|drop|delete|get rid|revert|undo|rename|reword|rephrase|"
    r"naming|name it|redundant|duplicat|unnecessary|needless|no need|prefer|style|tone|"
    r"comment|docstring|emoji|bullet|heading|header|markdown|format|"
    r"pr description|commit message|title|changelog|release note|"
    r"just|only|minimal|scope|keep it|leave|unrelated|hallucinat|sure\?|really\?|verify|"
    r"reproduce|repro|test it|confirm)\b",
    re.I,
)
CHORE = re.compile(r"^(merge|build\(deps\)|bump|ruff|mypy|lint|format|update snapshots?|fix$|wip)", re.I)


def norm(s):
    return re.sub(r"\W+", " ", s.lower()).strip()


def load_events():
    seen, out = set(), []
    for name in ("jsonl_events.jsonl", "txt_events.jsonl"):
        for e in read_jsonl(DATA / name):
            k = norm(e["text"])[:400]
            if k in seen:
                continue
            seen.add(k)
            out.append(e)
    return out


def fmt_event(e):
    where = e.get("session") or e.get("file")
    ts = (e.get("ts") or "")[:10]
    lines = [f"### [{e['kind']}] {e['project']} {ts} {where}"]
    if e["prior"]:
        lines.append("PRIOR (assistant):\n" + "\n".join("    " + l for l in clip(e["prior"], 700).splitlines()))
    lines.append("USER:\n" + "\n".join("    " + l for l in e["text"].splitlines()))
    return "\n".join(lines) + "\n"


def feedback(events):
    rev, other = [], []
    for e in events:
        if e["kind"] == "first":
            continue
        hit = e["kind"] in ("rejection", "interrupt") or REVISION.search(e["text"])
        (rev if hit else other).append(e)
    for name, rows in (("feedback_revisions.md", rev), ("feedback_other.md", other)):
        by_proj = defaultdict(list)
        for e in rows:
            by_proj[e["project"]].append(e)
        with open(DATA / name, "w") as f:
            for proj in sorted(by_proj):
                f.write(f"\n## {proj} ({len(by_proj[proj])})\n\n")
                for e in by_proj[proj]:
                    f.write(fmt_event(e) + "\n")
    return rev, other


def compact(rev, other):
    for name, rows in (("compact_revisions.txt", rev), ("compact_other.txt", other)):
        with open(DATA / name, "w") as f:
            for e in rows:
                t = re.sub(r"\s+", " ", e["text"])[:600]
                p = re.sub(r"\s+", " ", e["prior"])[:160]
                f.write(f"[{e['kind'][:3]}|{e['project'][:12]}] {t}\n    ^after: {p}\n")


def stats(events):
    c = Counter()
    for e in events:
        if e["kind"] == "first":
            continue
        for m in REVISION.finditer(e["text"]):
            c[m.group(0).lower()] += 1
    with open(DATA / "stats.md", "w") as f:
        for k, v in c.most_common():
            f.write(f"{v:5d} {k}\n")


def pr_digests():
    prs = [p for p in read_jsonl(DATA / "prs.jsonl") if p["createdAt"] >= since()]
    with open(DATA / "pr_body_diffs.md", "w") as f:
        n = 0
        for p in prs:
            edits = p["userContentEdits"]["nodes"]
            if not edits:
                continue
            first, last = (edits[-1]["diff"] or ""), (p["body"] or "")
            if norm(first) == norm(last):
                continue
            n += 1
            d = difflib.unified_diff(first.splitlines(), last.splitlines(), "original", "final", lineterm="", n=1)
            f.write(f"\n## {p['url']} — {p['title']}\n")
            f.write(f"original {len(first)} chars -> final {len(last)} chars, {len(edits)} edits\n```diff\n")
            f.write(clip("\n".join(d), 4000) + "\n```\n")
    with open(DATA / "pr_revisions.md", "w") as f:
        for p in prs:
            commits = [c["commit"] for c in p["commits"]["nodes"]]
            revs = [c for c in commits[1:] if not CHORE.match(c["message"].split("\n")[0])]
            reviews = [r for r in p["reviews"]["nodes"] if r["author"] and r["author"]["login"] != user()]
            if not revs and not reviews:
                continue
            f.write(f"\n## {p['url']} — {p['title']}\n")
            f.write(f"first: {commits[0]['message'].splitlines()[0] if commits else ''}\n")
            for r in reviews:
                bodies = [r["body"]] + [c["body"] for c in r["comments"]["nodes"]]
                bodies = [b for b in bodies if b and b.strip()]
                if bodies:
                    f.write(f"REVIEW {r['author']['login']} {r['state']}:\n")
                    for b in bodies:
                        f.write("    " + clip(b, 500).replace("\n", "\n    ") + "\n")
            for c in revs:
                f.write(f"\n### {c['message'].splitlines()[0]}  (+{c['additions']} -{c['deletions']})\n")
                body = "\n".join(c["message"].splitlines()[1:]).strip()
                body = re.sub(r"Co-Authored-By:.*", "", body, flags=re.I).strip()
                if body:
                    f.write(clip(body, 400) + "\n")
                if c["additions"] is not None and c["additions"] + c["deletions"] <= 80:
                    f.write("```diff\n" + clip(c.get("patch", ""), 1500) + "\n```\n")
    return n


def main():
    events = load_events()
    rev, other = feedback(events)
    compact(rev, other)
    stats(events)
    n = pr_digests()
    print(f"{len(events)} unique events: {len(rev)} revision-like, {len(other)} other; {n} PR body diffs")

