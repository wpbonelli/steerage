"""Fetch all the user's PRs with their commit series, body edit history and review comments.

Commits after the first in a PR are revision rounds; their messages and diffs
show what got changed after the initial attempt. Read-only GitHub access via `gh`.

Output: data/prs.jsonl, with patches cached under data/patches/.
"""

import json
import subprocess
import sys
import time
from datetime import date
from concurrent.futures import ThreadPoolExecutor

from .common import AGENT_TRAILER, DATA, first_year, user, write_jsonl

PATCHES = DATA / "patches"
YEARS = DATA / "search"

QUERY = """
query($q: String!, $n: Int!, $after: String) {
  search(query: $q, type: ISSUE, first: $n, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title body createdAt state merged url
      repository { nameWithOwner isPrivate }
      userContentEdits(first: 30) { nodes { createdAt diff editor { login __typename ... on User { name } } } }
      commits(first: 100) { nodes { commit {
        oid committedDate message additions deletions
      } } }
      reviews(first: 30) { nodes {
        author { login __typename ... on User { name } } state body submittedAt
        comments(first: 50) { nodes { body path diffHunk } }
      } }
      comments(first: 50) { nodes { author { login __typename ... on User { name } } body createdAt } }
    } }
  }
}
"""


def gh(*args) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def search_prs(q):
    after, prs = None, []
    while True:
        args = ["api", "graphql", "-f", f"query={QUERY}", "-f", f"q={q}"]
        if after:
            args += ["-f", f"after={after}"]
        # pages with large PRs can time out, so retry with smaller pages
        for i, n in enumerate((25, 10, 5, 1, 1, 1)):
            r = subprocess.run(["gh", *args, "-F", f"n={n}"], capture_output=True, text=True)
            try:
                # field errors, like an unavailable commit size, come with the rest of the page
                data = json.loads(r.stdout)["data"]
            except (ValueError, KeyError):
                data = None
            if data:
                s = data["search"]
                break
            print(f"  {n} per page failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            time.sleep(15 * (i + 1))
        else:
            raise RuntimeError(f"search failed: {q}")
        prs += [n for n in s["nodes"] if n]
        print(f"  {len(prs)} PRs", file=sys.stderr)
        if not s["pageInfo"]["hasNextPage"]:
            return prs
        after = s["pageInfo"]["endCursor"]


def year_prs(y: int):
    """Search returns at most 1000 results, so query a year at a time. Past years are cached."""
    cache = YEARS / f"{y}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    prs = search_prs(f"author:{user()} is:pr created:{y}-01-01..{y}-12-31")
    if y < date.today().year:
        cache.write_text(json.dumps(prs))
    return prs


def patch(repo: str, sha: str, limit=6000) -> str:
    cache = PATCHES / f"{sha}.diff"
    if cache.exists():
        return cache.read_text()
    try:
        text = gh("api", f"repos/{repo}/commits/{sha}", "-H", "Accept: application/vnd.github.diff")
    except subprocess.CalledProcessError as e:
        text = f"[error fetching patch: {e.stderr.strip()[:200]}]"
    text = text[:limit]
    cache.write_text(text)
    return text


def main():
    PATCHES.mkdir(exist_ok=True)
    YEARS.mkdir(exist_ok=True)
    prs = [pr for y in range(first_year(), date.today().year + 1) for pr in year_prs(y)]
    jobs = []
    for pr in prs:
        repo = pr["repository"]["nameWithOwner"]
        # a commit is null when GitHub can't compute one of its fields
        pr["commits"]["nodes"] = [c for c in pr["commits"]["nodes"] if c]
        commits = [c["commit"] for c in pr["commits"]["nodes"]]
        for c in commits:
            c["agent"] = AGENT_TRAILER in c["message"].lower()
        # revision rounds: everything after the first commit, skipping merges
        for c in commits[1:]:
            if not c["message"].lower().startswith("merge"):
                jobs.append((c, repo))
    print(f"fetching {len(jobs)} revision patches", file=sys.stderr)
    with ThreadPoolExecutor(8) as ex:
        for (c, repo), p in zip(jobs, ex.map(lambda j: patch(j[1], j[0]["oid"]), jobs)):
            c["patch"] = p
    n = write_jsonl(DATA / "prs.jsonl", prs)
    print(f"{n} PRs", file=sys.stderr)

