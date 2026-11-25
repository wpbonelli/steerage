"""Compare how the user revises agent drafts with how they revise their own, from data/pairs.jsonl.

For each kind, era and drafter: how much revisions shrink text, how often they remove
markup, and which words they delete or add across pairs. What the user cuts from
agent drafts but not from their own is an agent habit; what they cut from both is their style.

Output: data/eras.md
"""

import difflib
import re
import sys
from collections import Counter
from statistics import median

from .common import DATA, read_jsonl

MARKUP = {
    "heading": r"(?m)^#+ ",
    "bold": r"\*\*",
    "bullet": r"(?m)^\s*[-*] ",
    "code span": r"`[^`\n]+`",
    "table row": r"(?m)^\|",
    "dash": r"—| -- ",
}
WORD = re.compile(r"[a-z][a-z'-]+")


def changed_words(draft, final):
    """Words deleted and added by the revision, each counted once per pair."""
    a, b = WORD.findall(draft.lower()), WORD.findall(final.lower())
    gone, new = set(), set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            gone.update(a[i1:i2])
        if op in ("insert", "replace"):
            new.update(b[j1:j2])
    return gone - new, new - gone


def section(kind, era, drafter, pairs, top=20):
    n = len(pairs)
    ratio = median(len(r["final"]) / max(len(r["draft"]), 1) for r in pairs)
    out = [f"\n## {kind}, {era} era, drafter {drafter}: {n} pairs\n\n",
           f"Median final/draft length: {ratio:.2f}\n\n| markup | in drafts | removed | added |\n|---|---|---|---|\n"]
    for name, pat in MARKUP.items():
        d = [len(re.findall(pat, r["draft"])) for r in pairs]
        f = [len(re.findall(pat, r["final"])) for r in pairs]
        out.append(f"| {name} | {sum(x > 0 for x in d)} | {sum(x > y for x, y in zip(d, f))} "
                   f"| {sum(y > x for x, y in zip(d, f))} |\n")
    gone, new = Counter(), Counter()
    for r in pairs:
        g, a = changed_words(r["draft"], r["final"])
        gone.update(g)
        new.update(a)
    for label, c, other in [("Deleted", gone, new), ("Added", new, gone)]:
        words = [f"{w} ({k})" for w, k in c.most_common() if k >= max(2, n // 20) and k > 2 * other[w]][:top]
        out.append(f"\n{label} in more pairs than the reverse: {', '.join(words) or 'none'}\n")
    return "".join(out)


def main():
    pairs = [r for r in read_jsonl(DATA / "pairs.jsonl") if r["draft"] is not None]
    groups = Counter((r["kind"], r["era"], r["drafter"]) for r in pairs)
    out = ["# Revisions by era and drafter\n\nagent: drafts with an agent marker. self: drafts without one, the user's.\n"]
    for key in sorted(groups):
        out.append(section(*key, [r for r in pairs if (r["kind"], r["era"], r["drafter"]) == key]))
    (DATA / "eras.md").write_text("".join(out))
    print((DATA / "eras.md").read_text(), file=sys.stderr)

