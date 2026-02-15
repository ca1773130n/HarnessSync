---
name: harness:validate
description: Claude Code command: harness:validate
---
# /harness:validate

Run the project validation suite.

## Description

Executes all validation commands defined in `.claude/validation.json` and reports the results. This ensures code quality before completing tasks.

## Behavior

When invoked, perform the following steps:

1. **Load Configuration**
   - Read `.claude/validation.json` from the project root
   - If not found, offer to create one with sensible defaults

2. **Run Validations**
   - Execute each validation command in order
   - Report pass/fail status for each
   - Continue running all validations even if some fail

3. **Report Results**
   - Summary of passed/failed/skipped validations
   - Detailed output for failed validations
   - Overall status (pass if all required validations pass)

4. **Suggest Fixes**
   For common failures, suggest fixes:
   - Type errors: Show the specific errors and suggest fixes
   - Lint errors: Offer to run auto-fix if available
   - Test failures: Show which tests failed

## Example Output

```
## Running Validations

Running: typecheck... PASSED
Running: lint... FAILED
Running: test... PASSED

## Validation Results

Total: 3 validations
Passed: 2
Failed: 1

### Failed Validations

#### lint
Command: `npm run lint`

```
src/utils.ts:15:10: 'unused' is defined but never used
src/main.ts:42:5: Expected indentation of 2 spaces
```

**Suggestion:** Run `npm run lint -- --fix` to auto-fix some issues.

**Status:** Required validations failed
```

## Configuration

Create `.claude/validation.json`:

```json
{
  "commands": [
    {"name": "typecheck", "command": "npm run typecheck"},
    {"name": "lint", "command": "npm run lint"},
    {"name": "test", "command": "npm test"}
  ],
  "required": ["typecheck", "lint"]
}
```

## Script Location

`shared/scripts/validate.py`

## Related Commands

- `/harness:setup` - Set up project before validation
- `/harness:complete` - Complete task after validation passes


## When to Use This Skill

Claude Code command: harness:validate