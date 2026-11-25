"""Extract draft-vs-final text pairs from PR data, independent of any output format.

Each record is one piece of text and, where GitHub kept one, its earlier draft:

- pr-description: the final PR body and, if it was edited, the first body from
  the edit history.
- release-note: the first and last release note TOML description across a PR's
  revision commits. Release notes are MODFLOW 6's `doc/ReleaseNotes/items/*.toml`.
- pr-title, commit-subject: final text only. Titles of merged PRs become squash
  commit subjects; revision commit subjects are intermediate work.

Tags:

- drafter: "agent" when the draft carries an agent marker (`AGENT_*` in
  common.py), otherwise "self". This assumes agents always add the marker and
  the user removes it when editing a description, so no marker means the user
  wrote it.
  A PR's title has the drafter of its first description.
- era: "pre-agent" for PRs created before STEERAGE_SINCE, otherwise "agent".
- trigger: "review" when someone else reviewed the PR before the final revision,
  otherwise "self". Empty for records without a draft.
- public: the repository is public.

Also writes the people who took part in the PRs (the user, reviewers,
commenters, editors) as `login<TAB>name` lines, so output can be scrubbed of them.
The name is empty if the profile has none.

Output: data/pairs.jsonl, data/people.tsv
"""

import re
import sys
from collections import Counter

from .common import AGENT_BODY, AGENT_FOOTER, DATA, gh_user, read_jsonl, since, user, write_jsonl


def clean_body(text: str) -> str:
    text = AGENT_FOOTER.sub("", text or "")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # template checklists are boilerplate, not style
    text = "\n".join(l for l in text.splitlines() if not re.match(r"\s*[-*] \[[ xX]\]", l))
    text = re.sub(r"\n\s*([_-]{3,}\s*)?Checklist of items for pull request\s*$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def first_body(p):
    edits = p["userContentEdits"]["nodes"]
    return (edits[-1]["diff"] if edits else p["body"]) or ""


def record(p, kind, final, draft=None, drafter="self", revised=None, **extra):
    reviews = [r["submittedAt"] for r in p["reviews"]["nodes"]
               if (r["author"] or {}).get("login") != user() and r["submittedAt"]]
    trigger = None
    if draft is not None:
        trigger = "review" if revised and any(t < revised for t in reviews) else "self"
    return {"kind": kind, "repo": p["repository"]["nameWithOwner"], "number": p["number"],
            "url": p["url"], "title": p["title"], "created": p["createdAt"], "merged": p["merged"],
            **extra, "draft": draft, "final": final, "drafter": drafter,
            "era": "pre-agent" if p["createdAt"] < since() else "agent", "trigger": trigger,
            "public": not p["repository"]["isPrivate"]}


def pr_descriptions(prs):
    for p in prs:
        edits = p["userContentEdits"]["nodes"]
        raw = first_body(p)
        draft, final = clean_body(raw), clean_body(p["body"])
        if not final:
            continue
        drafter = "agent" if AGENT_BODY.search(raw) else "self"
        if draft != final:
            yield record(p, "pr-description", final, draft, revised=edits[0]["createdAt"], drafter=drafter)
        else:
            yield record(p, "pr-description", final, drafter=drafter)


def release_notes(prs):
    first, last = {}, {}
    for p in prs:
        commits = [c["commit"] for c in p["commits"]["nodes"]]
        for c in commits:
            for f in re.split(r"(?m)^diff --git ", c.get("patch") or ""):
                m = re.match(r"a/(doc/ReleaseNotes/items/\S+\.toml)", f)
                if not m:
                    continue
                old = re.findall(r'(?m)^-description = "(.*)"$', f)
                new = re.findall(r'(?m)^\+description = "(.*)"$', f)
                if not (old and new):
                    continue
                key = m.group(1)
                first.setdefault(key, (old[0], commits[0]["agent"]))
                last[key] = (new[-1], p, c["committedDate"])
    for key, (old, agent) in first.items():
        new, p, revised = last[key]
        if old != new:
            yield record(p, "release-note", unescape(new), unescape(old), revised=revised,
                         drafter="agent" if agent else "self", path=key)


def commits(prs):
    for p in prs:
        yield record(p, "pr-title", p["title"], drafter="agent" if AGENT_BODY.search(first_body(p)) else "self")
    for p in prs:
        for c in (c["commit"] for c in p["commits"]["nodes"][1:]):
            yield record(p, "commit-subject", c["message"].splitlines()[0].strip(),
                         drafter="agent" if c["agent"] else "self")


def people(prs):
    actors = [a for p in prs for a in (
        [e["editor"] for e in p["userContentEdits"]["nodes"]]
        + [r["author"] for r in p["reviews"]["nodes"]]
        + [c["author"] for c in p["comments"]["nodes"]])]
    found = {a["login"]: a.get("name") or "" for a in actors if a and a.get("__typename") == "User"}
    return found | {user(): gh_user().get("name") or ""}


def main():
    prs = list(read_jsonl(DATA / "prs.jsonl"))
    pairs = [*pr_descriptions(prs), *release_notes(prs), *commits(prs)]
    write_jsonl(DATA / "pairs.jsonl", pairs)
    (DATA / "people.tsv").write_text("".join(f"{l}\t{n}\n" for l, n in sorted(people(prs).items())))
    for k, n in Counter((r["kind"], r["era"], r["drafter"], r["trigger"]) for r in pairs).items():
        print(f"  {k}: {n}", file=sys.stderr)

