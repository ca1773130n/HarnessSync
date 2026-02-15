---
name: harness:setup
description: Claude Code command: harness:setup
---
# /harness:setup

Initialize and configure the project environment.

## Description

This command detects your project type, checks for missing dependencies, and offers to set up the development environment automatically.

## Behavior

When invoked, perform the following steps:

1. **Detect Project Type**
   - Run the detect-project.py script to identify the project type
   - Identify package manager and dependency status
   - Find existing context files (CLAUDE.md, validation.json, etc.)

2. **Report Findings**
   - Display detected project type(s)
   - Show package manager and dependency status
   - List context files found

3. **Offer Setup Actions**
   If dependencies are not installed, offer to install them:
   - For npm projects: `npm install`
   - For Python projects: `uv sync`, `poetry install`, or `pip install`
   - For Rust projects: `cargo build`
   - For Go projects: `go mod download`

4. **Create Missing Context Files**
   If CLAUDE.md doesn't exist, offer to create one from template.
   If .claude/validation.json doesn't exist, offer to create a default configuration.

## Example Output

```
## Project Setup

Detected: Node.js (TypeScript)
Package Manager: npm
Dependencies: Not installed

Context Files:
- README.md
- .github/CODEOWNERS

Recommendations:
1. Run `npm install` to install dependencies
2. Create CLAUDE.md for agent context
3. Create .claude/validation.json for validation

Would you like me to:
- [x] Install dependencies
- [x] Create CLAUDE.md from template
- [x] Create validation.json configuration
```

## Script Location

`shared/scripts/detect-project.py`

## Related Commands

- `/harness:validate` - Run validation after setup
- `/harness:prp` - Create a PRP for new tasks


## When to Use This Skill

Claude Code command: harness:setup