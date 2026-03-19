# HarnessSync Interactive Tutorial

Learn HarnessSync by building a real project. The `/sync-tutorial` command scaffolds a Python CLI app called **TaskFlow** and walks you through syncing every config surface to all 11 target harnesses, step by step.

## Prerequisites

- Claude Code installed
- HarnessSync plugin installed (`/install-plugin HarnessSync`)
- Python 3.9+

## Quick Start

```
/sync-tutorial start
```

This scaffolds a working TaskFlow todo app at `/tmp/taskflow-playground` and begins the guided tutorial. Run `/sync-tutorial next` to advance through each step.

## What You'll Learn

The tutorial covers 9 config surfaces in progressive steps:

| Step | Config Surface | What You'll See |
|------|---------------|----------------|
| 1 | **Setup** | Scaffold TaskFlow app, verify it works |
| 2 | **CLAUDE.md** | Project rules synced as `.cursorrules`, `AGENTS.md`, `GEMINI.md`, etc. |
| 3 | **Rules directory** | `.claude/rules/*.md` files merged into target configs |
| 4 | **Permissions** | `settings.json` allow/deny translated per harness |
| 5 | **Commands** | `/check` command represented as slash commands, aliases, or instructions |
| 6 | **Skills & Agents** | Skill/agent portability across harnesses that support them |
| 7 | **MCP Servers** | `.mcp.json` config synced to targets with native MCP support |
| 8 | **Hooks & Annotations** | Per-harness customization via `<!-- @harness: -->` comments |
| 9 | **Full Picture** | Dashboard, health check, and status report across all harnesses |

## Commands

| Command | Description |
|---------|------------|
| `/sync-tutorial start` | Begin the tutorial |
| `/sync-tutorial next` | Advance to next step |
| `/sync-tutorial status` | Show current progress |
| `/sync-tutorial goto N` | Jump to step N |
| `/sync-tutorial reset` | Start over |
| `/sync-tutorial cleanup` | Remove the tutorial project |

## The Example App: TaskFlow

TaskFlow is a Python CLI todo app with SQLite storage. It's not a toy — it has real models, a storage layer, a REST API, tests, and formatting. It exists to justify realistic AI coding rules, permissions, and workflows.

```
python3 -m taskflow add "Ship the feature" --priority high --tags release
python3 -m taskflow list
python3 -m taskflow complete 1
```

## Who This Is For

- **Plugin users** who want to see HarnessSync in action on a real project
- **Evaluators** deciding whether to adopt HarnessSync for their team
- **Power users** with 3+ AI harnesses who want to consolidate their config
