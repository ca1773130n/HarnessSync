# TaskFlow Tutorial — Interactive HarnessSync Playground

**Date:** 2026-03-19
**Status:** Draft
**Audience:** HarnessSync plugin users (power users with 3+ AI harnesses) and evaluators

## Problem

HarnessSync syncs Claude Code config to 12 AI harnesses, but new users have no way to see it in action. There's no example project, no tutorial, and no guided onboarding. Users must figure out the config surface, commands, and sync behavior on their own.

## Solution

An interactive tutorial skill (`/sync-tutorial`) that scaffolds a realistic Python CLI app called **TaskFlow** inside Claude Code. The tutorial walks users through 9 steps, each introducing a config layer (CLAUDE.md, rules, permissions, skills, agents, commands, MCP servers, hooks, annotations). After each step, the user runs real HarnessSync commands and inspects the generated target files.

## Design

### 1. The Example App — TaskFlow

A Python CLI todo app with ~200-300 lines of working code. It exists to justify every HarnessSync config surface with realistic, non-contrived rules.

#### App Structure

```
<target_dir>/
├── taskflow/
│   ├── __init__.py          # Package init, version string
│   ├── cli.py               # argparse CLI: add, list, complete, delete, search
│   ├── models.py            # Task dataclass: id, title, priority, tags, due_date, completed
│   ├── storage.py           # SQLite backend: CRUD operations, migrations
│   ├── api.py               # Minimal REST API using stdlib http.server
│   └── formatters.py        # Terminal output formatting (colors, tables)
├── tests/
│   ├── test_models.py       # Unit tests for Task dataclass
│   ├── test_storage.py      # Integration tests hitting real SQLite
│   └── test_cli.py          # CLI smoke tests
├── .claude/
│   ├── settings.json        # Permissions config
│   ├── rules/
│   │   ├── python.md        # Python conventions
│   │   └── testing.md       # Testing philosophy
│   ├── skills/
│   │   └── add-feature.md   # Guided feature addition skill
│   ├── agents/
│   │   └── reviewer.md      # Code review agent
│   └── commands/
│       └── check.md         # Combined lint + test command
├── .mcp.json                # MCP server config (SQLite explorer)
├── CLAUDE.md                # Project rules with harness annotations
├── hooks.json               # Pre-commit hooks config
└── README.md                # What TaskFlow is
```

#### Config Surface Justification

| Config Surface | What It Contains | Why It's Realistic |
|---------------|-----------------|-------------------|
| CLAUDE.md | Architecture rules, DB schema conventions, API patterns | Every project needs baseline rules |
| `.claude/rules/` | `python.md`: style, imports, typing. `testing.md`: pytest, real DB, no mocks | Separating concerns into rule files |
| Settings/permissions | Allow: pytest, sqlite3, python3. Deny: rm -rf, DROP TABLE | Security boundaries for AI tools |
| Skills | `add-feature.md`: guided workflow for adding a TaskFlow feature | Shows how skills transfer across harnesses |
| Agents | `reviewer.md`: code review agent with TaskFlow-specific context | Shows agent portability |
| Commands | `check.md`: runs ruff + pytest in one shot | Common developer workflow |
| MCP servers | SQLite explorer for the task database | Real tool integration |
| Hooks | Format-on-save, test-on-commit style hooks | Pre-commit patterns |
| Harness annotations | Per-harness rules (Cursor gets UI tips, Codex gets automation rules) | The killer feature of HarnessSync |

### 2. The Tutorial Skill

#### Entry Point

`commands/sync-tutorial.md` — a slash command that users invoke with `/sync-tutorial`.

#### Implementation

`src/commands/sync_tutorial.py` — the tutorial engine containing:

- **`scaffold_project(target_dir)`** — creates the base TaskFlow app (code only, no Claude config yet)
- **`add_step_files(target_dir, step_num)`** — adds the config files for a given step
- **`get_step_guide(step_num)`** — returns markdown guide text for a step (what was added, what to run, what to expect)
- **`load_state(target_dir)`** / **`save_state(target_dir, state)`** — read/write `.tutorial-state.json`

All file contents are embedded as Python string constants in the tutorial engine. No external template files, no Jinja — pure stdlib.

#### State Tracking

`.tutorial-state.json` in the scaffolded project:
```json
{
  "current_step": 3,
  "completed_steps": [1, 2, 3],
  "target_dir": "/tmp/taskflow-playground",
  "started_at": "2026-03-19T10:00:00Z",
  "harness_sync_version": "0.1.1"
}
```

The tutorial skill reads this file on each invocation to resume where the user left off.

### 3. Tutorial Steps

Each step follows a consistent pattern:
1. **Explain** what config layer is being introduced and why
2. **Add** the relevant config files to the project
3. **Instruct** the user to run specific HarnessSync commands
4. **Show** expected output and explain what happened in each target harness
5. **Highlight** key observations (e.g., "Notice how Codex got different rules than Cursor")

#### Step Breakdown

**Step 1: Setup**
- Scaffold TaskFlow app at user-chosen directory
- Verify HarnessSync plugin is installed
- Show the bare project structure
- User confirms app works: `python3 -m taskflow list`

**Step 2: CLAUDE.md — Project Rules**
- Add `CLAUDE.md` with architecture rules, DB conventions, API patterns
- User runs: `/sync`
- Inspect: `.cursorrules`, `AGENTS.md` (Codex), `GEMINI.md`, `.aider.conf.yml` etc.
- Highlight: same rules, different formats per harness

**Step 3: Rules Directory**
- Add `.claude/rules/python.md` and `.claude/rules/testing.md`
- User runs: `/sync`, `/sync-diff`
- Inspect: rules merged into target files
- Highlight: rule files get concatenated/structured differently per harness

**Step 4: Permissions**
- Add `.claude/settings.json` with allow/deny lists
- User runs: `/sync`, `/sync-status`
- Inspect: how permissions translate (Codex approval policy, Cursor allow lists, etc.)
- Highlight: Claude Code `deny` is never downgraded in targets

**Step 5: Skills & Agents**
- Add `.claude/skills/add-feature.md` and `.claude/agents/reviewer.md`
- User runs: `/sync`, `/sync-capabilities`
- Inspect: how skills/agents appear in each target
- Highlight: not all harnesses support skills/agents natively — show how HarnessSync adapts

**Step 6: Commands**
- Add `.claude/commands/check.md`
- User runs: `/sync`
- Inspect: command representation across targets
- Highlight: commands as slash commands vs. shell aliases vs. embedded instructions

**Step 7: MCP Servers**
- Add `.mcp.json` with a SQLite explorer server config
- User runs: `/sync`, `/sync-status`
- Inspect: MCP config in targets that support it
- Highlight: which harnesses support MCP natively vs. where it becomes documentation

**Step 8: Hooks & Annotations**
- Add `hooks.json` with format-on-save hook
- Add harness annotations to `CLAUDE.md`:
  ```markdown
  <!-- @harness: cursor, windsurf -->
  Use integrated terminal for testing.
  <!-- @harness: codex -->
  All tests must be fully automated.
  <!-- @harness: * -->
  All endpoints return JSON.
  ```
- User runs: `/sync`, `/sync-matrix`
- Inspect: different content in different target files
- Highlight: this is the killer feature — per-harness customization from a single source

**Step 9: Full Picture**
- No new files — this is the victory lap
- User runs: `/sync-dashboard`, `/sync-health`, `/sync-report`
- See the complete sync state across all harnesses
- Show the user how to maintain this going forward

### 4. Slash Command Definition

`commands/sync-tutorial.md`:
```markdown
---
name: sync-tutorial
description: Interactive tutorial — scaffold a TaskFlow example project and learn HarnessSync step by step
arguments:
  - name: action
    description: "start, next, reset, or status (default: next)"
    required: false
  - name: directory
    description: "Target directory for the example project"
    required: false
---
```

Actions:
- **`start`** — scaffold project, begin at step 1
- **`next`** (default) — advance to next step
- **`reset`** — remove state, start over
- **`status`** — show current step and progress

### 5. File Inventory

Files to create:

| File | Purpose | ~Size |
|------|---------|-------|
| `commands/sync-tutorial.md` | Slash command definition | ~20 lines |
| `src/commands/sync_tutorial.py` | Tutorial engine + all embedded templates | ~800-1000 lines |
| `examples/taskflow/README.md` | Static reference doc for GitHub browsing | ~100 lines |

The tutorial engine (`sync_tutorial.py`) is the only substantial file. It contains:
- All TaskFlow app source code as string constants
- All Claude config file contents as string constants
- Step guide text for each of the 9 steps
- Scaffolding and state management logic

### 6. Design Decisions

**Why embed templates as strings instead of files?**
- No template engine dependency (stdlib only)
- Can't drift from the tutorial logic
- Single file to maintain
- Consistent with existing HarnessSync adapter patterns

**Why `/tmp` as default target?**
- Doesn't pollute user's workspace
- Easy to clean up
- No risk of overwriting real projects

**Why state file in the project dir?**
- Travels with the project if user moves it
- Easy to inspect and debug
- Clean separation from HarnessSync plugin state

**Why 9 steps and not fewer?**
- Each step introduces exactly one config surface
- Users can stop at any point and still have a working example
- Steps 1-4 cover 80% of use cases; steps 5-9 are for power users who want the full picture

### 7. Success Criteria

- [ ] User can run `/sync-tutorial start` and have a working TaskFlow project in <10 seconds
- [ ] Each step adds exactly one config layer and explains it clearly
- [ ] After each step, at least one `/sync-*` command shows meaningful output
- [ ] The tutorial works on macOS (primary) and Linux
- [ ] Step 8 (annotations) clearly demonstrates per-harness differentiation
- [ ] Step 9 gives users confidence they understand HarnessSync's full capability
- [ ] `examples/taskflow/README.md` is useful for GitHub browsers who don't run the tutorial
- [ ] All TaskFlow code is real, working Python that passes its own tests
