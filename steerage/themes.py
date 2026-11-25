"""Count follow-up turns matching each revision theme in THEMES.

The themes are the author's; edit them for yours.

Output: data/themes.md
"""

import re
import sys

from .common import DATA
from .digest import load_events

THEMES = {
    "terse / shorter / condense": r"\b(terse|tersen|tersify|shorter|condense|concise|trim|brief|verbose|as terse)\b",
    "in my style / sound like me / my tone": r"\b(my style|my tone|sound like me|keep my|in my terse)\b",
    "don't run full tests, CI can": r"(ci can|let ci|targeted test|full (test )?suite|full smoke|don't run (the )?(tests|all)|don't worry about (running )?(the )?tests)",
    "suggest PR description (I'll open)": r"(suggest (a |an )?(terse |updated |new )?pr description|i'll open the pr|don't open)",
    "release note for the user": r"release note.*(user|clear)|user.(oriented|facing|in mind)",
    "think it through, don't change yet": r"(don't (start|change|proceed|put)|just (think|talk)|before (you|changing|we begin|starting)|walk me through)",
    "write up a local doc/plan": r"(write (up |down )?(a |the )?(local )?(plan|doc)|local (plan|doc)|planning doc)",
    "unclear: what do you mean": r"(what do you mean|i don't (quite )?(understand|follow|get)|i'm (confused|not sure i (understand|follow))|explain)",
    "are you sure / verify / repro": r"(are you sure|you're sure|confirm|reproduce|repro\b|did you (check|verify|reproduce))",
    "simpler / overkill / too much code": r"(simpl|overkill|too complicated|a lot of code|less code|fewer loc|trying (a bit )?too hard|minimal)",
    "scope: separate branch/PR": r"(separate (branch|pr)|new (branch|worktree)|out of scope|in this pr\?|keep this pr)",
    "don't describe old behavior in tests/comments": r"(what used to|old behavior|what was wrong|describe what('s| is) expected)",
    "no names of routines/variables": r"(variable names|routine names|without mentioning specific|conceptual terms|concepts not)",
    "github markdown / clipboard": r"(github markdown|clipboard|backticks)",
}


def main():
    ev = [e for e in load_events() if e["kind"] != "first"]
    with open(DATA / "themes.md", "w") as f:
        f.write(f"Follow-up turns: {len(ev)}\n\n| theme | turns | example |\n|---|---|---|\n")
        for name, pat in THEMES.items():
            hits = [e for e in ev if re.search(pat, e["text"], re.I)]
            ex = re.sub(r"\s+", " ", min(hits, key=lambda e: len(e["text"]))["text"])[:90] if hits else ""
            f.write(f"| {name} | {len(hits)} | {ex.replace('|', '/')} |\n")
    print((DATA / "themes.md").read_text(), file=sys.stderr)

