"""Claude Code transcripts: user turns with the preceding assistant context.

Reads session transcripts under `~/.claude/projects/*/*.jsonl`, and conversation
text exports under the projects root. Exports use `❯ ` for user turns and `⏺ `
for assistant turns, with 2-space continuation lines.

Output: data/jsonl_events.jsonl, data/txt_events.jsonl
"""

import json
import os
import re
import sys
from pathlib import Path

from .common import DATA, NOISE, ROOT, SKIP, clip, write_jsonl

PROJECTS = Path.home() / ".claude" / "projects"
PRUNE = {".git", "node_modules", ".pixi", ".venv", "venv", "build", "_build"}
TOOL_LINE = re.compile(r"^⏺ [A-Z][\w-]*\(")  # ⏺ Bash(...), ⏺ Update(...)
REJECT = re.compile(r"User rejected|user said:", re.I)


def folder(path: Path) -> str:
    """Name of the transcript folder for a project path."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def strip_tags(text: str) -> str:
    """Drop harness-injected blocks."""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    text = re.sub(r"<(command|local-command)[^>]*>.*?</\1[^>]*>", "", text, flags=re.S)
    text = re.sub(r"<(task-notification|tools-used-before-summary)>.*?</\1>", "", text, flags=re.S)
    text = re.sub(r"^\s*(Ran|Read|Listed|Searched for|Wrote|Updated) \d+ .*\(ctrl\+o to expand\)\s*$", "", text, flags=re.M)
    text = text.replace("The user doesn't want to proceed with this tool use. The tool use was rejected "
                        "(eg. if it was a file edit, the new_string was NOT written to the file).", "")
    text = text.replace("STOP what you are doing and wait for the user to tell you how to proceed.", "")
    return text.strip()


def is_harness(text: str) -> bool:
    """Compaction summaries and other non-user content in the user role."""
    return text.lstrip().startswith(("This session is being continued", "<task-notification",
                                     "Caveat:", "[Image", "Base directory for this skill"))


def user_text(msg) -> str | None:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [x.get("text", "") for x in c if x.get("type") == "text"]
        return "\n".join(parts) if parts else None
    return None


def tool_rejection(msg) -> str | None:
    c = msg.get("content")
    if not isinstance(c, list):
        return None
    for x in c:
        if x.get("type") != "tool_result":
            continue
        body = x.get("content")
        if isinstance(body, list):
            body = "\n".join(b.get("text", "") for b in body if isinstance(b, dict))
        body = body or ""
        if "user said:" in body or ("doesn't want to proceed" in body and x.get("is_error")):
            return body
    return None


def jsonl_events(path: Path):
    project = path.parent.name.removeprefix(folder(ROOT) + "-")
    last_text = ""  # last assistant prose
    last_tool = ""  # last assistant tool call summary
    seen_assistant = False
    interrupted = False
    for line in open(path):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t, msg = d.get("type"), d.get("message")
        if not isinstance(msg, dict):
            continue
        if t == "assistant":
            for x in msg.get("content") or []:
                if x.get("type") == "text" and x["text"].strip():
                    last_text = x["text"]
                    last_tool = ""
                elif x.get("type") == "tool_use":
                    inp = x.get("input", {})
                    last_tool = f"{x.get('name')}: " + clip(json.dumps(inp), 1500)
            seen_assistant = True
            continue
        if t != "user" or d.get("isMeta") or d.get("isCompactSummary"):
            continue
        base = dict(source="jsonl", project=project, session=path.stem, ts=d.get("timestamp"))
        rej = tool_rejection(msg)
        if rej:
            yield dict(base, kind="rejection", prior=clip(last_tool or last_text, 1500), text=clip(strip_tags(rej), 2000))
            continue
        text = user_text(msg)
        if text is None:
            continue
        if text.startswith("[Request interrupted"):
            interrupted = True
            continue
        text = strip_tags(text)
        if not text or is_harness(text) or NOISE.match(text):
            continue
        kind = "first" if not seen_assistant else ("interrupt" if interrupted else "followup")
        interrupted = False
        yield dict(base, kind=kind, prior=clip(last_text, 1500), text=clip(text, 3000))


def find_exports():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in PRUNE and Path(dirpath, d) not in SKIP]
        depth = len(Path(dirpath).relative_to(ROOT).parts)
        if depth > 3:
            dirnames[:] = []
        for f in filenames:
            if f.endswith(".txt"):
                p = Path(dirpath) / f
                try:
                    head = p.read_text(errors="ignore")
                except OSError:
                    continue
                if "\n❯ " in head or head.startswith("❯ "):
                    yield p, head


def blocks(text: str):
    """Yield (role, lines) blocks."""
    role, buf = None, []
    for line in text.splitlines():
        if line.startswith("❯ "):
            if role:
                yield role, buf
            role, buf = "user", [line[2:]]
        elif line.startswith("⏺ "):
            if role:
                yield role, buf
            role = "tool" if TOOL_LINE.match(line) else "assistant"
            buf = [line[2:]]
        elif role:
            buf.append(line[2:] if line.startswith("  ") else line)
    if role:
        yield role, buf


def clean_user(lines):
    # export wraps long input with trailing padding; rejoin and drop UI chrome
    out = []
    for l in lines:
        if re.match(r"^\s*(⎿|✻|─{5,}|\? for shortcuts)", l):
            break
        out.append(l.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def txt_events(path: Path, text: str):
    rel = path.relative_to(ROOT)
    project = rel.parts[0]
    mtime = path.stat().st_mtime
    last_text, last_tool, seen_assistant = "", "", False
    for role, lines in blocks(text):
        body = "\n".join(lines).strip()
        if role == "assistant":
            last_text, last_tool, seen_assistant = body, "", True
            continue
        if role == "tool":
            last_tool = clip(body, 1500)
            seen_assistant = True
            m = REJECT.search(body)
            if m:
                yield dict(source="txt", project=project, file=str(rel), mtime=mtime, kind="rejection",
                           prior=last_tool, text=clip(body[m.start():], 1500))
            continue
        u = strip_tags(clean_user(lines))
        if not u or is_harness(u) or NOISE.match(u):
            continue
        kind = "followup" if seen_assistant else "first"
        yield dict(source="txt", project=project, file=str(rel), mtime=mtime, kind=kind,
                   prior=clip(last_text, 1500), text=clip(u, 3000))


def main():
    skip = {folder(p) for p in SKIP}
    files = [p for p in PROJECTS.glob("*/*.jsonl") if p.parent.name not in skip]
    n = write_jsonl(DATA / "jsonl_events.jsonl", (e for p in sorted(files) for e in jsonl_events(p)))
    print(f"{n} events from {len(files)} sessions", file=sys.stderr)

    rows, nfiles = [], 0
    for p, text in find_exports():
        nfiles += 1
        rows.extend(txt_events(p, text))
    n = write_jsonl(DATA / "txt_events.jsonl", rows)
    print(f"{n} events from {nfiles} export files", file=sys.stderr)
