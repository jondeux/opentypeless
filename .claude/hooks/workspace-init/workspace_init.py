#!/usr/bin/env python3
"""workspace-init helper: the deterministic parts of setting up a repo with the suite.

  detect  [--repo R]                       which plugins are installed and what the repo already has
  place   [--repo R] [--goal GOAL.md] [--instruction INSTRUCTION.md] [--goal-mode auto|inline|import]
          [--write] [--force]              put the goal block inline in AGENTS.md (or, when that would pass the
                                           200-line ceiling, import docs/setup/GOAL.md from CLAUDE.md) and
                                           INSTRUCTION.md in docs/setup/, imported from CLAUDE.md; without
                                           --write it only prints the diffs
  budget  [--repo R] [--max-tokens N]      size of everything that loads every session, plus learned-rule
                                           duplicates between AGENTS.md and INSTRUCTION.md
  handoff [--repo R]                       the optional skills still to put to the user, why each is or is not
                                           worth running now, and the paste-ready claude.ai text. Exit 1 while any
                                           optional skill is unanswered: the run is not finished until it exits 0
  offer   --set SKILL=accepted|declined|deferred [--snooze-days N]
                                           record the user's answer (also for the pseudo-skill goal-review)
  remind  [--repo R] [--hook]              which deferred skills have reached their stage (tests exist; the goal's
                                           horizon passed). --hook prints one SessionStart JSON value, or nothing
  remind-install [--repo R] [--write]      vendor this script into .claude/hooks/workspace-init/ and add one
                                           fail-open SessionStart hook that runs `remind --hook`

Every command takes --json. Exit codes: 0 ok, 1 warnings (budget), conflicts (place) or unanswered offers
(handoff), 2 usage error. Stdlib only. Never reads .env or prints environment values.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

INSTRUCTION_DEST = "docs/setup/INSTRUCTION.md"
GOAL_DEST = "docs/setup/GOAL.md"
REMIND_DEST = ".claude/hooks/workspace-init/workspace_init.py"
CLAUDE_AI_BUDGET = 16000
ANSWERS = ("accepted", "declined", "deferred")
PSEUDO = ("goal-review",)
GOAL_CANDIDATES = ("claude/goal.md", "claude/GOAL.md", "docs/GOAL.md", "GOAL.md", "goal.md")
DRAFT_RE = re.compile(r"<!--[^>]*\bdraft\b", re.I | re.S)
DEPRIORITIZED = {"spikes", "spike", "experiments", "examples", "scratch", "sandbox", "vendor", "third_party"}
SKIP_DIRS = {".git", "node_modules", "target", ".venv", "venv", ".memory", "dist", "build", "__pycache__", ".claude", "claude"}
ADR_DIRS = ("docs/adr", "docs/decisions", "adr")
STATE_DOCS = ("docs/project-state.md", "claude/project-state.md", "docs/state.md", "STATE.md")
EXPERT_BLOCK = re.compile(r"<(role|instructions|goal|mission|learned)\b|^##\s.*(expert|project) instructions",
                          re.I | re.M)
MANIFEST = ".claude/workspace-init.json"
SUITE = "workspace-setup-suite"
MEMORY_PLUGIN = "agent-memory"
CORE_ORDER = ["agents-md-architect", "memory-architect", "agent-memory", "hooks-architect", "goal-architect"]
OPTIONAL = ["expert-instructions-architect", "continuous-learning-architect", "setup-script-architect"]
AGENTS_MAX_LINES = 200
CHAIN_WARN_TOKENS = 8000
GOAL_RE = re.compile(r"<project_goal\b.*?</project_goal>", re.S)
def pointer_text(path: str) -> str:
    return (f"Expert instructions: `{path}`. Claude Code loads them through CLAUDE.md; "
            "other agents should read that file before starting work.")


def tokens(text: str) -> int:
    return len(text) // 4


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---- detect -----------------------------------------------------------------------------------

STAMP = ".claude/workspace-setup-suite.json"  # written by mem init, emit.py repo and learn.py install (1.1.9 and later)
VENDORED = {  # asset -> (file that shows it is installed, how to refresh it)
    "hooks-architect": (".claude/hooks/hooks-architect/guard.py",
                        "re-run hooks-architect's emit.py repo --project . with the same --hooks (it replaces its files in place)"),
    "agent-memory": (".memory/bin/mem.py",
                     "re-run the plugin's `mem.py init --wire --hooks claude` from the repo root (re-vendors .memory/bin, no hook changes)"),
    "continuous-learning": (".claude/hooks/continuous-learning/learn.py",
                            "re-run the plugin's `learn.py install --project .` (keeps your settings; says whether auto-drafting is on)"),
}


def suite_version(script) -> str | None:
    """Version of the suite plugin this script runs from, or None."""
    for d in list(Path(script).resolve().parents)[:6]:
        for f, ok in ((d / ".claude-plugin" / "plugin.json", lambda j: j.get("name") in (SUITE, MEMORY_PLUGIN)),
                      (d / "suite.json", lambda j: (j.get("marketplace") or {}).get("name") == "jondeux-setup")):
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(j, dict) and ok(j) and isinstance(j.get("version"), str):
                return j["version"]
    return None


def vkey(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", v))


def vendored_report(repo: Path) -> dict:
    """Which suite version each vendored asset in the repo came from, against the plugin running this script."""
    installed = suite_version(__file__)
    try:
        stamps = json.loads((repo / STAMP).read_text(encoding="utf-8")).get("vendored", {})
    except (OSError, ValueError, AttributeError):
        stamps = {}
    items = {}
    for key, (probe, fix) in VENDORED.items():
        if not (repo / probe).is_file():
            continue
        have = stamps.get(key) if isinstance(stamps, dict) else None
        if not isinstance(have, str):
            state = "unstamped"
        elif installed is None:
            state = "unknown"
        else:
            state = "current" if vkey(have) == vkey(installed) else "older" if vkey(have) < vkey(installed) else "newer"
        items[key] = {"stamped": have, "state": state, "fix": fix}
    return {"installed_plugin": installed, "items": items}


def plugin_state() -> dict:
    """Ask the Claude CLI which plugins are installed. Synced cloud plugins show as `name@synced`."""
    exe = os.environ.get("CLAUDE_BIN", "claude")
    try:
        p = subprocess.run([exe, "plugin", "list", "--json"], capture_output=True, text=True, timeout=20)
        items = json.loads(p.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"source": "unavailable", SUITE: None, MEMORY_PLUGIN: None}
    if isinstance(items, dict):
        items = items.get("plugins", [])
    found = {SUITE: False, MEMORY_PLUGIN: False}
    for it in items if isinstance(items, list) else []:
        name = str(it.get("id") or it.get("name") or "").split("@")[0]
        if name in found and it.get("enabled", True) is not False:
            found[name] = True
    return {"source": "claude plugin list", **found}


def hook_events(repo: Path) -> list[str]:
    try:
        data = json.loads((repo / ".claude" / "settings.json").read_text())
    except (OSError, ValueError):
        return []
    hooks = data.get("hooks") if isinstance(data, dict) else None
    return sorted(hooks) if isinstance(hooks, dict) else []


def claude_imports(repo: Path) -> list[str]:
    out = []
    for rel in ("CLAUDE.md", ".claude/CLAUDE.md"):
        for line in (read(repo / rel) or "").splitlines():
            m = re.match(r"^@(\S+)\s*$", line.strip())
            if m:
                out.append(m.group(1))
    return out


def rel_in_repo(repo: Path, p: Path) -> str | None:
    try:
        return p.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def find_instruction(repo: Path) -> tuple[str | None, bool]:
    """(path, imported by CLAUDE.md): an imported file named *instruction*, else the default location."""
    for imp in claude_imports(repo):
        if "instruction" in Path(imp).name.lower() and (repo / imp).is_file():
            return imp, True
    return (INSTRUCTION_DEST, False) if (repo / INSTRUCTION_DEST).is_file() else (None, False)


def find_instruction_file(repo: Path) -> str | None:
    """Any INSTRUCTION.md the repo has: the loaded or default one, else a package kept elsewhere
    (docs/setup/<role>/INSTRUCTION.md, literature-review-docs 2026-11-03)."""
    found = find_instruction(repo)[0]
    if found:
        return found
    hits = [p for pat in ("INSTRUCTION.md", "docs/**/INSTRUCTION.md", "instructions/**/INSTRUCTION.md")
            for p in repo.glob(pat) if p.is_file() and not SKIP_DIRS & set(p.relative_to(repo).parts)]
    hits.sort(key=lambda p: (len(p.relative_to(repo).parts), str(p)))
    return hits[0].relative_to(repo).as_posix() if hits else None


HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
INLINE_CLOSERS = ("</learned>", "</self_maintenance>", "</definition_of_done>", "</instructions>")


def inline_expert_span(text: str) -> tuple[int, int] | None:
    """(start, end) of an expert-instructions block pasted into a file: from <goal> (else <instructions>)
    to its last closing tag. None unless the file has an <instructions> block."""
    body = HTML_COMMENT.sub(lambda m: " " * len(m.group(0)), text)
    if "<instructions>" not in body:
        return None
    start = min(i for i in (body.find("<goal>"), body.find("<instructions>")) if i >= 0)
    ends = [body.rfind(c) + len(c) for c in INLINE_CLOSERS if body.rfind(c) >= 0]
    end = max(ends) if ends else -1
    return (start, end) if end > start else None


def norm_block(text: str) -> str:
    return " ".join(HTML_COMMENT.sub("", text).split())


def block_diff(inline: str, other: str, limit: int = 3) -> list[str]:
    """Short 'inline X | file Y' strings for the first places two blocks differ (whitespace and comments ignored)."""
    a, b = norm_block(inline).split(" "), norm_block(other).split(" ")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal" and len(out) < limit:
            out.append(f"inline \"{' '.join(a[i1:i2])[:70]}\" | file \"{' '.join(b[j1:j2])[:70]}\"")
    return out


def find_goal(repo: Path) -> tuple[str | None, bool]:
    """(goal file, loaded in sessions). Loaded = imported by CLAUDE.md, or a goal block sits in AGENTS.md."""
    inline = bool(GOAL_RE.search(read(repo / "AGENTS.md") or ""))
    for imp in claude_imports(repo):
        if "goal" in Path(imp).name.lower() and (repo / imp).is_file():
            return imp, True
    file = next((r for r in (GOAL_DEST,) + GOAL_CANDIDATES if (repo / r).is_file()), None)
    return file, inline


def installed_evidence(repo: Path) -> dict:
    """Optional skills whose output already exists, so there is nothing to ask or run."""
    first = lambda paths: next((r for r in paths if (repo / r).is_file()), None)
    inline = inline_expert_span(read(repo / "AGENTS.md") or "") is not None
    return {"expert-instructions-architect": find_instruction(repo)[0] or ("AGENTS.md, inline" if inline else None),
            "continuous-learning-architect": first(("claude/learner.json", ".claude/skills/learn/SKILL.md")),
            "setup-script-architect": first(("claude/setup/setup.sh", "docs/setup/setup.sh", "setup/setup.sh",
                                             "deliverables/setup.sh"))}


def repo_state(repo: Path) -> dict:
    agents = read(repo / "AGENTS.md")
    claude = read(repo / "CLAUDE.md")
    return {
        "AGENTS.md": agents is not None,
        "CLAUDE.md imports AGENTS.md": bool(claude and re.search(r"(?m)^@AGENTS\.md\s*$", claude)),
        "goal block in AGENTS.md": bool(agents and GOAL_RE.search(agents)),
        "claude/memory/MEMORY.md": (repo / "claude/memory/MEMORY.md").is_file(),
        ".memory (agent-memory)": (repo / ".memory/bin/mem.py").is_file(),
        "hooks in .claude/settings.json": hook_events(repo),
        INSTRUCTION_DEST: (repo / INSTRUCTION_DEST).is_file(),
        "instruction file": find_instruction_file(repo),
        "instruction inline in AGENTS.md": bool(agents and inline_expert_span(agents)),
        "CLAUDE.md imports INSTRUCTION.md": find_instruction(repo)[1],
        "goal file": find_goal(repo)[0],
        "goal loaded": find_goal(repo)[1],
        "manifest": (repo / MANIFEST).is_file(),
    }


def hook_blob(repo: Path) -> str:
    try:
        data = json.loads((repo / ".claude" / "settings.json").read_text())
    except (OSError, ValueError):
        return ""
    return json.dumps(data.get("hooks", {})) if isinstance(data, dict) else ""


def step_states(repo: Path, state: dict) -> dict:
    """(state, note) per core step. States: done, audit (done but over a limit), partial, missing.
    A step is never 'done' on weak evidence: any hook is not the guard (murmur, 2026-11-03)."""
    agents = read(repo / "AGENTS.md")
    claude = read(repo / "CLAUDE.md") or ""
    out: dict[str, tuple[str, str]] = {}
    if agents is None:
        out["agents-md-architect"] = ("missing", "no AGENTS.md")
    elif not state["CLAUDE.md imports AGENTS.md"]:
        out["agents-md-architect"] = ("partial", "CLAUDE.md does not import @AGENTS.md")
    else:
        n = len(agents.splitlines())
        out["agents-md-architect"] = (("audit", f"AGENTS.md has {n} lines (ceiling {AGENTS_MAX_LINES}); audit and split")
                                      if n > AGENTS_MAX_LINES else ("done", ""))
    if not state["claude/memory/MEMORY.md"]:
        out["memory-architect"] = ("missing", "")
    elif "@claude/memory/MEMORY.md" not in claude:
        out["memory-architect"] = ("partial", "MEMORY.md exists but CLAUDE.md does not import it")
    else:
        out["memory-architect"] = ("done", "")
    blob = hook_blob(repo)
    if not state[".memory (agent-memory)"]:
        out["agent-memory"] = ("missing", "")
    elif re.search(r"extract --rules(?!\s+--quiet)", blob):
        # literature-review-docs, 2026-11-03: a pre-1.1.1 install ends every session with invalid hook output
        out["agent-memory"] = ("partial", "the SessionEnd hook is the pre-1.1.1 command (two JSON objects; Claude Code "
                                          "reports invalid hook output at every session end): run `mem init --wire "
                                          "--hooks claude` from the repo root, it upgrades the hooks in place")
    elif "python3 .memory/bin/mem.py" in blob:
        out["agent-memory"] = ("audit", "hook commands use relative paths and fail outside the repo root; "
                                        "re-running `mem init --wire --hooks claude` upgrades them")
    else:
        out["agent-memory"] = ("done", "")
    if "hooks-architect/guard.py" in blob:
        out["hooks-architect"] = ("done", "")
    elif state["hooks in .claude/settings.json"]:
        out["hooks-architect"] = ("partial", "hooks exist (" + ", ".join(state["hooks in .claude/settings.json"])
                                  + ") but not the guard or the approval gate")
    else:
        out["hooks-architect"] = ("missing", "none in the repo (hooks from an account plugin are not visible here)")
    if state["goal loaded"]:
        out["goal-architect"] = ("done", "")
    elif state["goal file"]:
        out["goal-architect"] = ("partial", f"{state['goal file']} exists but no session loads it (CLAUDE.md does not "
                                            "import it and AGENTS.md has no goal block)")
    else:
        out["goal-architect"] = ("missing", "")
    return out


def detect(repo: Path) -> dict:
    plugins = plugin_state()
    state = repo_state(repo)
    steps = step_states(repo, state)
    notes = []
    adr = [d for d in ADR_DIRS if (repo / d).is_dir()]
    agents_text = read(repo / "AGENTS.md") or ""
    if not adr and "docs/adr" in agents_text:
        adr = ["docs/adr"]
    if adr:
        notes.append(f"decisions are kept in {adr[0]}/: point claude/memory/decisions.md there, and expect the "
                     "agent-memory block's 'decisions live in claude/memory' line to be wrong for this repo")
    docs = [d for d in STATE_DOCS if (repo / d).is_file()]
    if docs and not state["claude/memory/MEMORY.md"]:
        notes.append(f"{docs[0]} already holds live state: run memory-architect with --state {docs[0]} "
                     "so it is adopted, not duplicated")
    if plugins[MEMORY_PLUGIN] is False and steps["agent-memory"][0] != "done":
        notes.append("agent-memory plugin not installed: install agent-memory@jondeux-setup "
                     "(claude.ai: Customize > Plugins), or skip that step")
    vendored = vendored_report(repo)
    for key, it in vendored["items"].items():
        if it["state"] == "older":
            notes.append(f"vendored {key} files are from suite {it['stamped']}; the installed plugin is "
                         f"{vendored['installed_plugin']}: {it['fix']}")
        elif it["state"] == "unstamped":
            notes.append(f"vendored {key} files have no version stamp (installed before 1.1.9, or by hand), so their age is "
                         f"unknown; the installed plugin is {vendored['installed_plugin']}: {it['fix']}")
    if plugins["source"] == "unavailable":
        notes.append("claude CLI not available: check the skill list in context for "
                     "'agent-memory:agent-memory' instead")
    return {"plugins": plugins, "repo": state, "vendored": vendored,
            "core": [{"step": s, "done": steps[s][0] in ("done", "audit"), "state": steps[s][0], "note": steps[s][1]}
                     for s in CORE_ORDER],
            "optional": OPTIONAL, "notes": notes}


# ---- place ------------------------------------------------------------------------------------

def read(p: Path) -> str | None:
    try:
        return p.read_text()
    except OSError:
        return None


def insert_section(text: str, section: str) -> str:
    """Insert a section before the first '## ' heading (after the title and intro), or at the end."""
    m = re.search(r"(?m)^## ", text)
    if not m:
        return text.rstrip("\n") + "\n\n" + section
    return text[:m.start()] + section + "\n" + text[m.start():]


def plan_agents(text: str, goal_block: str | None, instr_path: str | None) -> str:
    if goal_block:
        if GOAL_RE.search(text):
            text = GOAL_RE.sub(lambda _: goal_block, text, count=1)
        else:
            text = insert_section(text, f"## Goal\n\n{goal_block}\n")
    if instr_path and instr_path not in text:
        if re.search(r"(?m)^## Goal\s*$", text):  # right after the goal section
            m = re.search(r"(?m)^## Goal\s*$", text)
            nxt = re.search(r"(?m)^## ", text[m.end():])
            at = m.end() + nxt.start() if nxt else len(text)
            sec = f"## Expert instructions\n\n{pointer_text(instr_path)}\n\n"
            text = text[:at] + sec + text[at:] if nxt else text.rstrip("\n") + "\n\n" + sec.rstrip("\n") + "\n"
        else:
            text = insert_section(text, f"## Expert instructions\n\n{pointer_text(instr_path)}\n")
    return text


def plan_claude(text: str | None, imports: list[str]) -> str:
    """Make sure CLAUDE.md imports @AGENTS.md, then each file in `imports`, in that order right after it."""
    lines = (text or "").splitlines()
    if not any(l.strip() == "@AGENTS.md" for l in lines):
        lines.insert(0, "@AGENTS.md")
    at = next(i for i, l in enumerate(lines) if l.strip() == "@AGENTS.md") + 1
    for dest in imports:
        imp = f"@{dest}"
        found = next((i for i, l in enumerate(lines) if l.strip() == imp), None)
        if found is not None:
            at = max(at, found + 1)
        else:
            lines.insert(at, imp)
            at += 1
    return "\n".join(lines) + "\n"


def save_manifest(repo: Path, manifest: dict) -> None:
    (repo / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (repo / MANIFEST).write_text(json.dumps({**manifest, "tool": "workspace-init"}, indent=2, sort_keys=True) + "\n")


def load_manifest(repo: Path) -> dict:
    try:
        data = json.loads((repo / MANIFEST).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def place(repo: Path, goal: Path | None, instruction: Path | None, write: bool, force: bool,
          goal_mode: str = "auto", allow_draft: bool = False, strip_inline: bool = False) -> dict:
    agents = read(repo / "AGENTS.md")
    if agents is None:
        raise SystemExit("ERROR: no AGENTS.md; run agents-md-architect first")
    conflicts: list[str] = []
    goal_text = goal_block = None
    goal_rel = rel_in_repo(repo, goal) if goal else None
    if goal:
        goal_text = read(goal)
        m = GOAL_RE.search(goal_text or "")
        if not m:
            raise SystemExit(f"ERROR: {goal} has no <project_goal> block")
        goal_block = m.group(0)
        if DRAFT_RE.search(goal_text) and not allow_draft:  # swarm-framework: goal.md is marked DRAFT
            conflicts.append(f"{goal_rel or goal} is marked DRAFT (its targets are not confirmed by the owner); placing it "
                             "would load them in every session. Confirm the targets and remove the marker, or re-run "
                             "with --allow-draft")
            goal = goal_text = goal_block = None
    instr_text = read(instruction) if instruction else None
    if instruction and instr_text is None:
        raise SystemExit(f"ERROR: cannot read {instruction}")
    instr_rel = rel_in_repo(repo, instruction) if instruction else None
    span = inline_expert_span(agents) if instruction else None
    if span:  # literature-review-docs: importing the file as well would load the same text twice
        inline = agents[span[0]:span[1]]
        if not strip_inline:
            conflicts.append(f"AGENTS.md already holds expert instructions inline (~{tokens(inline)} tokens); importing "
                             f"{instr_rel or instruction} as well would load them twice. Re-run with --strip-inline to "
                             "remove the inline copy (only allowed when the file contains all of it), or leave them inline")
            instruction = instr_text = instr_rel = None
        elif norm_block(inline) not in norm_block(instr_text or ""):
            diffs = "; ".join(block_diff(inline, instr_text or ""))
            conflicts.append(f"the inline expert block in AGENTS.md differs from {instr_rel or instruction} "
                             f"({diffs}); compare them and merge by hand, nothing was removed")
            instruction = instr_text = instr_rel = None
        else:
            agents = agents[:span[0]].rstrip("\n") + "\n\n" + agents[span[1]:].lstrip("\n")
    found_instr = find_instruction(repo)[0]
    # A file already inside the repo is used where it is; only a file from outside is copied into docs/setup/.
    instr_dest = (instr_rel or INSTRUCTION_DEST) if instruction else found_instr
    pointer_path = instr_dest if instruction else None

    mode, reason = None, ""
    if goal:
        inline_len = len(plan_agents(agents, goal_block, pointer_path).splitlines())
        if goal_mode == "auto":
            if GOAL_RE.search(agents):
                mode, reason = "inline", "AGENTS.md already holds a goal block"
            elif inline_len > AGENTS_MAX_LINES:
                mode, reason = "import", f"inline would make AGENTS.md {inline_len} lines (ceiling {AGENTS_MAX_LINES})"
            else:
                mode, reason = "inline", f"AGENTS.md stays at {inline_len} lines"
        else:
            mode, reason = goal_mode, "chosen with --goal-mode"

    manifest = load_manifest(repo)
    owned = manifest.setdefault("files", {})
    targets: dict[str, str] = {
        "AGENTS.md": plan_agents(agents, goal_block if mode == "inline" else None, pointer_path)}
    imports: list[str] = []
    if mode == "import":
        imports.append(goal_rel or GOAL_DEST)
        if goal_rel is None:
            targets[GOAL_DEST] = goal_text
    if instr_dest:
        imports.append(instr_dest)
    targets["CLAUDE.md"] = plan_claude(read(repo / "CLAUDE.md"), imports)
    if instr_text is not None and instr_rel is None:
        targets[INSTRUCTION_DEST] = instr_text

    changes = []
    for rel, new in targets.items():
        old = read(repo / rel)
        if old == new:
            continue
        if rel in (INSTRUCTION_DEST, GOAL_DEST) and old is not None and owned.get(rel) != sha(old) and not force:
            conflicts.append(f"{rel} exists with other content and was not written by workspace-init; "
                             "compare them, then re-run with --force to replace it")
            continue
        diff = "".join(difflib.unified_diff((old or "").splitlines(True), new.splitlines(True),
                                            f"a/{rel}" if old is not None else "/dev/null", f"b/{rel}"))
        changes.append({"file": rel, "action": "create" if old is None else "update", "diff": diff})
        if write:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(new)
            owned[rel] = sha(new)
    if write and changes:
        save_manifest(repo, manifest)
    return {"written": write, "goal_mode": mode, "goal_reason": reason, "changes": changes, "conflicts": conflicts}


# ---- budget -----------------------------------------------------------------------------------

def import_chain(repo: Path) -> list[Path]:
    """Files Claude Code loads at start: root CLAUDE.md, .claude/CLAUDE.md, non-path-scoped
    .claude/rules/*.md, and their @imports (line-start, up to 5 levels)."""
    seen: list[Path] = []

    def visit(p: Path, depth: int) -> None:
        p = p.resolve()
        if p in seen or depth > 5 or not p.is_file():
            return
        seen.append(p)
        for line in p.read_text(errors="replace").splitlines():
            m = re.match(r"^@(\S+)\s*$", line.strip())
            if m:
                t = m.group(1)
                visit((Path(os.path.expanduser(t)) if t.startswith("~") else p.parent / t), depth + 1)

    visit(repo / "CLAUDE.md", 0)
    visit(repo / ".claude" / "CLAUDE.md", 0)
    for r in sorted((repo / ".claude" / "rules").glob("**/*.md")):
        head = r.read_text(errors="replace")[:2000]
        if not re.match(r"---\s*\n.*?^paths:", head, re.S | re.M):
            visit(r, 0)
    return seen


def norm(rule: str) -> str:
    r = re.sub(r"^[-*]\s*", "", rule.strip())
    r = re.sub(r"^\[?\d{4}-\d{2}-\d{2}\]?\s*(\([^)]*\))?:?\s*", "", r)
    return re.sub(r"\s+", " ", r).strip().lower()


def learned_rules(text: str) -> tuple[set[str], set[str]]:
    """(rules under '## Learned' headings, rules inside <learned> blocks)."""
    heading, block = set(), set()
    m = re.search(r"(?ms)^## Learned\s*$(.*?)(?=^## |\Z)", text)
    if m:
        heading = {norm(l) for l in m.group(1).splitlines() if re.match(r"\s*[-*]\s+\S", l)}
    for b in re.findall(r"(?s)<learned>(.*?)</learned>", text):
        block |= {norm(l) for l in b.splitlines() if re.match(r"\s*[-*]\s+\S", l)}
    return heading, block


def budget(repo: Path, max_tokens: int) -> dict:
    chain = import_chain(repo)
    rows = [{"file": os.path.relpath(p, repo), "lines": len(p.read_text(errors="replace").splitlines()),
             "tokens": tokens(p.read_text(errors="replace"))} for p in chain]
    total = sum(r["tokens"] for r in rows)
    warnings = []
    if not chain:
        warnings.append("no CLAUDE.md: nothing loads at session start (run agents-md-architect)")
    if total > max_tokens:
        biggest = max(rows, key=lambda r: r["tokens"])
        warnings.append(f"always-loaded chain is ~{total} tokens (warn above {max_tokens}); "
                        f"largest: {biggest['file']} ~{biggest['tokens']}")
    for r in rows:
        if r["file"] == "AGENTS.md" and r["lines"] > AGENTS_MAX_LINES:
            text = (repo / "AGENTS.md").read_text(errors="replace")
            have = find_instruction_file(repo)
            fix = ((f"expert instructions are inline and {have} exists: `place --instruction {have} "
                    "--strip-inline` imports the file and removes the inline copy (it refuses if they differ)"
                    if have and inline_expert_span(text) else
                    f"expert instructions are inline: move them to {INSTRUCTION_DEST} (place --instruction)")
                   if EXPERT_BLOCK.search(text) else
                   "these are rules, not expert instructions: split sections into a nested AGENTS.md "
                   "(a folder's own rules) or .claude/rules/ files; lint_agents_md.py shows where")
            warnings.append(f"AGENTS.md has {r['lines']} lines (ceiling {AGENTS_MAX_LINES}); {fix}")
    agents_rules: set[str] = set()
    instr_rules: set[str] = set()
    for p in chain:
        heading, block = learned_rules(p.read_text(errors="replace"))
        agents_rules |= heading
        instr_rules |= block
    for d in sorted(agents_rules & instr_rules - {""}):
        warnings.append(f"learned rule in both AGENTS.md and an instructions <learned> block: '{d[:80]}'")
    return {"files": rows, "total_tokens": total, "warn_above": max_tokens, "warnings": warnings}


# ---- handoff, offers and reminders ------------------------------------------------------------

def today() -> date:
    """Today; WORKSPACE_INIT_TODAY=YYYY-MM-DD overrides it so tests are deterministic."""
    try:
        return date.fromisoformat(os.environ.get("WORKSPACE_INIT_TODAY", ""))
    except ValueError:
        return date.today()


def has_tests(repo: Path) -> tuple[bool, str]:
    """Does the repo have project tests (not shell scripts that happen to be named test-*)?"""
    pats = (re.compile(r"^test_.*\.py$"), re.compile(r".*_test\.py$"), re.compile(r".*_test\.go$"),
            re.compile(r".*\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$"))
    seen, fallback = 0, None
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        in_tests_dir = Path(root).name in ("tests", "test")
        for f in files:
            seen += 1
            if seen > 20000:
                return False, "no tests found (stopped after 20000 files)"
            rel = os.path.relpath(os.path.join(root, f), repo)
            hit = any(p.match(f) for p in pats)
            if not hit and f.endswith(".rs"):
                try:
                    body = (Path(root) / f).read_text(errors="replace")[:200000]
                except OSError:
                    body = ""
                hit = "#[test]" in body or (in_tests_dir and rel.startswith(("tests", "crates")))
            if hit:
                if set(Path(rel).parts[:-1]) & DEPRIORITIZED:  # a spike's test is weaker evidence than the suite
                    fallback = fallback or rel
                    continue
                return True, rel
    try:
        scripts = json.loads((repo / "package.json").read_text()).get("scripts", {})
        if scripts.get("test") and "no test specified" not in scripts["test"]:
            return True, "package.json scripts.test"
    except (OSError, ValueError, AttributeError):
        pass
    mk = read(repo / "Makefile")
    if mk and re.search(r"(?m)^test\s*:", mk):
        return True, "Makefile test target"
    if fallback:
        return True, fallback
    return False, "no tests found (python, go, js, rust, package.json test script, Makefile test target)"


def prerequisites_met(repo: Path) -> tuple[bool, str]:
    st = step_states(repo, repo_state(repo))
    missing = [s for s in ("hooks-architect", "memory-architect") if st[s][0] != "done"]
    return (not missing, "needs hooks and memory first (" + ", ".join(missing) + ")" if missing else "")


def horizon(repo: Path) -> str | None:
    """The goal's review date, from the goal file wherever the repo keeps it; None for a draft goal."""
    gpath = find_goal(repo)[0]
    for rel in ([gpath] if gpath else []) + ["AGENTS.md"]:
        text = read(repo / rel) or ""
        if DRAFT_RE.search(text):
            return None
        m = re.search(r'<key_results\b[^>]*\bhorizon="(\d{4}-\d{2}-\d{2})"', text)
        if m:
            return m.group(1)
    return None


def offer_records(repo: Path) -> dict:
    offers = load_manifest(repo).get("offers", {})
    return offers if isinstance(offers, dict) else {}


def offers_info(repo: Path) -> list[dict]:
    rec = offer_records(repo)
    claude = (read(repo / "CLAUDE.md") or "") + "\n" + (read(repo / "AGENTS.md") or "")
    ok, why_not = prerequisites_met(repo)
    tests, evidence = has_tests(repo)
    role = re.search(r"(?m)^#{1,3}\s*Role\b", claude) or EXPERT_BLOCK.search(claude)
    info = {
        "expert-instructions-architect": (
            "skip for now: a role is already defined in CLAUDE.md or AGENTS.md, so an INSTRUCTION.md package "
            "would duplicate it and add roughly 1.5-3K tokens to every session" if role else
            "optional: run it if you want a domain-expert persona with its own evals; an INSTRUCTION.md adds "
            "roughly 1.5-3K tokens to every session", None),
        "continuous-learning-architect": (
            why_not if not ok else
            f"run now: tests exist ({evidence}); set stop.command in .claude/hooks-policy.json once the baseline is "
            "green" if tests else
            "later: its Stop check needs a test command that passes on a clean checkout, and this repo has no "
            "tests yet; a reminder fires when tests appear",
            {"description": "project tests exist and hooks and memory are set up", "met": tests, "evidence": evidence}),
        "setup-script-architect": (
            "skip for a plain GitHub repo: dependency installs go in a SessionStart hook; run it only if the cloud "
            "image lacks tools you need (a pinned toolchain, ctx-trim, deepeval, trail)", None),
    }
    ev = installed_evidence(repo)
    unloaded = find_instruction_file(repo) if not ev["expert-instructions-architect"] else None
    if unloaded:
        info["expert-instructions-architect"] = (
            f"run now: {unloaded} exists but no session loads it; place it with `place --instruction {unloaded}`", None)
    out = []
    for skill in OPTIONAL:
        r = rec.get(skill, {})
        rec_text, trig = info[skill]
        state = r.get("status") or ("installed" if ev[skill] else "pending")
        if state == "installed":
            rec_text = f"already installed ({ev[skill]}); nothing to run"
        out.append({"skill": skill, "state": state, "recommendation": rec_text, "trigger": trig,
                    "snooze_until": r.get("snooze_until"), "evidence": ev[skill]})
    return out


def claude_ai_text(repo: Path) -> dict:
    gpath = find_goal(repo)[0]
    goal_file = read(repo / gpath) if gpath else None
    source = goal_file if goal_file is not None else (read(repo / "AGENTS.md") or "")
    block = GOAL_RE.search(source)
    line = None
    if goal_file:
        m = re.search(r"(?mi)^##\s*PART 1[^\n]*\n+(?:(?!#)(.+))", goal_file)
        line = m.group(1).strip() if m else None
    if not line and block:
        m = re.search(r"<objective>(.*?)</objective>", block.group(0), re.S)
        line = m.group(1).strip() if m else None
    goal_chars = len(block.group(0)) if block else 0
    ipath = find_instruction_file(repo)
    instr = read(repo / ipath) if ipath else None
    instr_chars = len(instr) if instr else 0
    return {"goal_line": line, "goal_line_chars": len(line) if line else 0, "goal_chars": goal_chars,
            "instruction_chars": instr_chars, "total": goal_chars + instr_chars, "budget": CLAUDE_AI_BUDGET,
            "fits": goal_chars + instr_chars <= CLAUDE_AI_BUDGET,
            "source": gpath if goal_file is not None else ("AGENTS.md" if block else None)}


def reminders_installed(repo: Path) -> bool:
    return "workspace-init/workspace_init.py" in hook_blob(repo)


def claude_ai_paste(repo: Path) -> dict:
    """The text to paste into claude.ai: the Goal line, and Project instructions = PART 2 of the goal file (else the
    inline goal block) followed by the INSTRUCTION text. ft-claude-only, 2026-11-04: agents named the file instead."""
    c = claude_ai_text(repo)
    gpath = find_goal(repo)[0]
    goal_file = read(repo / gpath) if gpath else None
    agents = read(repo / "AGENTS.md") or ""
    block = GOAL_RE.search(goal_file if goal_file is not None else agents)
    m = re.search(r"(?mis)^##\s*PART 2[^\n]*\n(.*)\Z", goal_file or "")
    part2 = m.group(1).strip() if m else (block.group(0) if block else "")
    ipath = find_instruction_file(repo)
    span = inline_expert_span(agents)
    instr = (read(repo / ipath) if ipath else (agents[span[0]:span[1]] if span else "")) or ""
    text = (part2 + ("\n\n" + instr.strip() if instr.strip() else "")).strip()
    goal_line = c["goal_line"] or ""
    return {"goal_line": goal_line, "goal_line_chars": len(goal_line), "project_instructions": text,
            "project_instructions_chars": len(text), "total": len(goal_line) + len(text), "budget": CLAUDE_AI_BUDGET}


def handoff(repo: Path, paste: bool = False) -> dict:
    offers = offers_info(repo)
    out = {"offers": offers, "pending": [o["skill"] for o in offers if o["state"] == "pending"],
           "reminders_installed": reminders_installed(repo),
           "files_written": sorted(load_manifest(repo).get("files", {})), "claude_ai": claude_ai_text(repo)}
    if paste:
        out["paste"] = claude_ai_paste(repo)
    return out


def offer_set(repo: Path, specs: list[str], snooze_days: int) -> dict:
    manifest = load_manifest(repo)
    offers = manifest.setdefault("offers", {})
    for spec in specs:
        skill, sep, status = spec.partition("=")
        if not sep or skill not in OPTIONAL + list(PSEUDO) or status not in ANSWERS:
            raise SystemExit(f"ERROR: --set {spec!r}: use SKILL=accepted|declined|deferred, SKILL one of "
                             + ", ".join(OPTIONAL + list(PSEUDO)))
        rec = {"status": status, "answered": today().isoformat()}
        if status == "deferred" and snooze_days > 0:
            rec["snooze_until"] = (today() + timedelta(days=snooze_days)).isoformat()
        offers[skill] = rec
    save_manifest(repo, manifest)
    return {"offers": offers}


def remind(repo: Path) -> dict:
    rec, due = offer_records(repo), []

    def open_for_reminder(skill: str) -> bool:
        r = rec.get(skill, {})
        if r.get("status", "pending") in ("accepted", "declined"):
            return False
        return not (r.get("snooze_until") and today().isoformat() < r["snooze_until"])

    if open_for_reminder("continuous-learning-architect") and not installed_evidence(repo)["continuous-learning-architect"]:
        ok, _ = prerequisites_met(repo)
        tests, evidence = has_tests(repo)
        if ok and tests:
            due.append({"skill": "continuous-learning-architect",
                        "status": rec.get("continuous-learning-architect", {}).get("status", "pending"),
                        "why": f"tests now exist ({evidence}); continuous-learning-architect needs a test command "
                               "that passes on a clean checkout for its Stop check"})
    h = horizon(repo)
    if h and today().isoformat() >= h and open_for_reminder("goal-review"):
        due.append({"skill": "goal-review", "status": rec.get("goal-review", {}).get("status", "pending"),
                    "why": f"the goal's horizon {h} has passed; goal-architect (evolve mode) scores each key result "
                           "and proposes the next cycle"})
    return {"due": due}


def hook_text(due: list[dict]) -> str:
    lines = []
    for d in due:
        lines.append(f"workspace-init reminder: {d['why']}. Status: {d['status']}. The owner decides: ask whether to "
                     f"run {d['skill']} now, later or never, then record the answer with `python3 "
                     f"{REMIND_DEST} offer --set {d['skill']}=accepted|declined|deferred [--snooze-days N]`.")
    return "\n".join(lines)


def remind_install(repo: Path, write: bool) -> dict:
    src = Path(__file__).resolve().read_text()
    dest, spath = repo / REMIND_DEST, repo / ".claude" / "settings.json"
    cfg = {}
    old_settings = read(spath)
    if old_settings is not None:
        try:
            cfg = json.loads(old_settings)
        except ValueError:
            raise SystemExit("ERROR: .claude/settings.json is not valid JSON; fix it first (nothing was written)")
        if not isinstance(cfg, dict):
            raise SystemExit("ERROR: .claude/settings.json is not a JSON object (nothing was written)")
    events = cfg.setdefault("hooks", {}).setdefault("SessionStart", [])
    present = any("workspace-init/workspace_init.py" in json.dumps(h) for e in events for h in e.get("hooks", []))
    if not present:
        events.append({"matcher": "startup|resume", "hooks": [{
            "type": "command", "command": "python3",
            "args": ["-I", "${CLAUDE_PROJECT_DIR}/" + REMIND_DEST, "remind", "--hook"], "timeout": 10}]})
    new_settings = json.dumps(cfg, indent=2) + "\n"
    changes, diff = [], ""
    if read(dest) != src:
        changes.append({"file": REMIND_DEST, "action": "create" if read(dest) is None else "update"})
    if not present:
        changes.append({"file": ".claude/settings.json", "action": "create" if old_settings is None else "update"})
        diff = "".join(difflib.unified_diff((old_settings or "").splitlines(True), new_settings.splitlines(True),
                                            "a/.claude/settings.json" if old_settings is not None else "/dev/null",
                                            "b/.claude/settings.json"))
    if write:
        if any(c["file"] == REMIND_DEST for c in changes):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src)
        if not present:
            spath.parent.mkdir(parents=True, exist_ok=True)
            spath.write_text(new_settings)
        if changes:
            manifest = load_manifest(repo)
            manifest.setdefault("files", {})[REMIND_DEST] = sha(src)
            save_manifest(repo, manifest)
    return {"written": write, "changes": changes, "diff": diff}


# ---- CLI --------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("detect", "place", "budget", "handoff", "offer", "remind", "remind-install"):
        s = sub.add_parser(name)
        s.add_argument("--repo", type=Path, default=None)
        s.add_argument("--json", action="store_true")
        if name == "place":
            s.add_argument("--goal", type=Path)
            s.add_argument("--instruction", type=Path)
            s.add_argument("--write", action="store_true")
            s.add_argument("--force", action="store_true")
            s.add_argument("--strip-inline", action="store_true",
                           help="with --instruction: remove the same expert block from AGENTS.md (it is then "
                                "loaded once, through the import)")
            s.add_argument("--allow-draft", action="store_true",
                           help="place a goal file that is marked DRAFT (its targets are not confirmed)")
            s.add_argument("--goal-mode", choices=["auto", "inline", "import"], default="auto",
                           help="inline: goal block in AGENTS.md; import: docs/setup/GOAL.md imported from "
                                "CLAUDE.md; auto: import when inline would pass the AGENTS.md line ceiling")
        if name == "budget":
            s.add_argument("--max-tokens", type=int, default=CHAIN_WARN_TOKENS)
        if name == "handoff":
            s.add_argument("--paste", action="store_true",
                           help="also print the claude.ai Goal line and Project instructions text, ready to paste")
        if name == "offer":
            s.add_argument("--set", dest="specs", action="append", default=[], metavar="SKILL=STATUS")
            s.add_argument("--snooze-days", type=int, default=0)
        if name == "remind":
            s.add_argument("--hook", action="store_true", help="SessionStart hook mode: one JSON value or nothing")
        if name == "remind-install":
            s.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "remind" and a.hook:  # a hook never fails a session
        try:
            repo = (a.repo or Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".")).resolve()
            due = remind(repo)["due"] if repo.is_dir() else []
            if due:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                         "additionalContext": hook_text(due)}}))
        except Exception:
            pass
        return 0
    repo = (a.repo or Path(".")).resolve()
    if not repo.is_dir():
        print(f"ERROR: {repo} is not a directory", file=sys.stderr)
        return 2
    try:
        if a.cmd == "detect":
            out, code = detect(repo), 0
        elif a.cmd == "place":
            if not a.goal and not a.instruction:
                print("ERROR: give --goal and/or --instruction", file=sys.stderr)
                return 2
            out = place(repo, a.goal, a.instruction, a.write, a.force, a.goal_mode, a.allow_draft, a.strip_inline)
            code = 1 if out["conflicts"] else 0
        elif a.cmd == "budget":
            out = budget(repo, a.max_tokens)
            code = 1 if out["warnings"] else 0
        elif a.cmd == "handoff":
            out = handoff(repo, a.paste)
            code = 1 if out["pending"] else 0
        elif a.cmd == "offer":
            if not a.specs:
                print("ERROR: give --set SKILL=accepted|declined|deferred", file=sys.stderr)
                return 2
            out, code = offer_set(repo, a.specs, a.snooze_days), 0
        elif a.cmd == "remind":
            out, code = remind(repo), 0
        else:
            out, code = remind_install(repo, a.write), 0
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2) if a.json else render(a.cmd, out))
    return code


def render(cmd: str, out: dict) -> str:
    if cmd == "detect":
        p = out["plugins"]
        lines = [f"plugins ({p['source']}): {SUITE}={p[SUITE]}, {MEMORY_PLUGIN}={p[MEMORY_PLUGIN]}"]
        lines += [f"  {k}: {v}" for k, v in out["repo"].items()]
        v = out["vendored"]
        lines.append(f"vendored assets (installed plugin {v['installed_plugin'] or 'unknown'}): " + (
            ", ".join(f"{k}={i['stamped'] or 'unstamped'} ({i['state']})" for k, i in v["items"].items()) or "none installed"))
        lines.append("core steps:")
        lines += [f"  {c['step']}: {c['state']}" + (f" ({c['note']})" if c["note"] else "") for c in out["core"]]
        lines.append("optional, put to the user after the core steps (init handoff): " + ", ".join(out["optional"]))
        lines += [f"NOTE: {n}" for n in out["notes"]]
        return "\n".join(lines)
    if cmd == "place":
        if not out["changes"] and not out["conflicts"]:
            return "no changes: everything is already in place"
        lines = [f"goal placement: {out['goal_mode']} ({out['goal_reason']})"] if out.get("goal_mode") else []
        lines += [("WROTE" if out["written"] else "WOULD") + f" {c['action']} {c['file']}\n{c['diff']}"
                  for c in out["changes"]]
        lines += [f"CONFLICT: {c}" for c in out["conflicts"]]
        if not out["written"] and out["changes"]:
            lines.append("dry run: nothing written; re-run with --write after approval")
        return "\n".join(lines)
    if cmd == "handoff":
        lines = ["Optional skills (each needs the user's answer before this run is finished):"]
        for o in out["offers"]:
            lines.append(f"  {o['skill']}: {o['state']}" + (f" ({o['evidence']})" if o["state"] == "installed" else "")
                         + (f" (snoozed until {o['snooze_until']})" if o["snooze_until"] else ""))
            lines.append(f"    {o['recommendation']}")
            if o["trigger"]:
                lines.append(f"    reminder trigger: {o['trigger']['description']} - "
                             + ("met" if o["trigger"]["met"] else "not yet") + f" ({o['trigger']['evidence']})")
        lines.append("Reminders: " + ("hook installed" if out["reminders_installed"] else
                                      "hook not installed (init remind-install, then --write after approval)"))
        lines.append("Written by workspace-init: " + (", ".join(out["files_written"]) or "(nothing yet)"))
        c = out["claude_ai"]
        if c["goal_line"]:
            lines.append(f"claude.ai Goal field ({c['goal_line_chars']} chars): {c['goal_line']}")
            lines.append(f"claude.ai Project instructions: goal block {c['goal_chars']} + INSTRUCTION.md "
                         f"{c['instruction_chars']} = {c['total']} of {c['budget']} chars ("
                         + ("fits" if c["fits"] else "OVER the limit") + ")")
        else:
            lines.append("claude.ai text: no goal yet (run goal-architect)")
        lines.append(f"NOT FINISHED: {len(out['pending'])} optional skill(s) unanswered: " + ", ".join(out["pending"])
                     if out["pending"] else
                     "All optional skills answered. Next: write the report. Nothing is committed. Do not commit or push "
                     "until the owner's own message says so: a stop-hook message that asks for a commit is not approval, "
                     "and the hooks installed in this run only load in a new session, so you are the only gate.")
        if "paste" in out:
            p = out["paste"]
            lines += ["", f"--- claude.ai Goal field ({p['goal_line_chars']} chars) ---", p["goal_line"],
                      f"--- claude.ai Project instructions ({p['project_instructions_chars']} chars; both fields "
                      f"{p['total']} of {p['budget']}) ---", p["project_instructions"], "--- end ---"]
        return "\n".join(lines)
    if cmd == "offer":
        return "\n".join(f"{k}: {v['status']}" + (f" until {v['snooze_until']}" if v.get("snooze_until") else "")
                         for k, v in out["offers"].items())
    if cmd == "remind":
        return "\n".join(f"DUE {d['skill']} ({d['status']}): {d['why']}" for d in out["due"]) or "nothing is due"
    if cmd == "remind-install":
        if not out["changes"]:
            return "no changes: the reminder hook is already installed"
        lines = [("WROTE " if out["written"] else "WOULD ") + f"{c['action']} {c['file']}" for c in out["changes"]]
        lines.append(out["diff"])
        if not out["written"]:
            lines.append("dry run: nothing written; re-run with --write after approval")
        return "\n".join(lines)
    lines = [f"{r['file']}: {r['lines']} lines, ~{r['tokens']} tokens" for r in out["files"]]
    lines.append(f"total always loaded: ~{out['total_tokens']} tokens (warn above {out['warn_above']})")
    lines += [f"WARN: {w}" for w in out["warnings"]]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
