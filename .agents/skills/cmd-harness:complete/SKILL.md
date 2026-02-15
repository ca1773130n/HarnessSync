---
name: harness:complete
description: Claude Code command: harness:complete
---
# /harness:complete

Mark a task as complete with validation.

## Description

Finalizes a task by running all validations, generating a completion summary, and emitting the completion token for the Ralph Loop.

## Behavior

When invoked, perform the following steps:

1. **Run Full Validation Suite**
   - Execute all validations from `.claude/validation.json`
   - All required validations must pass to complete

2. **Review Changes**
   - Summarize files modified during the task
   - List new files created
   - Note any deleted files

3. **Check Acceptance Criteria**
   If a PRP exists for this task:
   - Review each acceptance criterion
   - Confirm all criteria are met
   - Note any criteria that need attention

4. **Generate Summary**
   Create a completion summary including:
   - What was implemented
   - Files changed
   - Tests added/modified
   - Any known limitations or follow-up tasks

5. **Emit Completion Token**
   If all validations pass and criteria are met:
   - Output `<promise>COMPLETE</promise>`
   - This signals the Ralph Loop that the task is done

6. **Handle Failures**
   If validations fail:
   - Do NOT emit completion token
   - Show what failed
   - Suggest fixes
   - Offer to continue working

## Example Output (Success)

```
## Task Completion Check

### Validations
- typecheck: PASSED
- lint: PASSED
- test: PASSED

### Changes Summary
Modified: 5 files
Created: 2 files
Deleted: 0 files

### Files Changed
- src/auth/jwt.ts (created)
- src/middleware/auth.ts (created)
- src/routes/auth.ts (modified)
- src/routes/api.ts (modified)
- tests/auth.test.ts (created)

### Acceptance Criteria
- [x] JWT token generation on login
- [x] Token verification middleware
- [x] Protected API endpoints
- [x] Token refresh mechanism

### Summary
Implemented JWT-based authentication with login/logout endpoints,
middleware protection for API routes, and comprehensive test coverage.

<promise>COMPLETE</promise>

Task completed successfully! Ready for review.
```

## Example Output (Failure)

```
## Task Completion Check

### Validations
- typecheck: PASSED
- lint: FAILED
- test: PASSED

### Validation Failures

#### lint
```
src/auth/jwt.ts:25:1: Unexpected console statement
```

**Cannot complete task.** Please fix the lint errors and try again.

Run `/harness:validate` to see full details.
```

## Script Location

`shared/scripts/completion-check.py`

## Related Commands

- `/harness:validate` - Run validations without completing
- `/harness:prp` - View the PRP for this task


## When to Use This Skill

Claude Code command: harness:complete