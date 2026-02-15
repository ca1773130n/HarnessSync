---
name: harness:prp
description: Claude Code command: harness:prp
---
# /harness:prp

Generate a Product Requirement Prompt (PRP) document.

## Description

Creates a structured PRP document from natural language requirements. PRPs provide clear specifications for tasks, making it easier to track progress and validate completion.

## Behavior

When invoked, perform the following steps:

1. **Gather Requirements**
   If no arguments provided, ask the user for:
   - Feature/task name
   - Problem being solved
   - High-level goals
   - Any technical constraints

2. **Analyze Codebase** (if applicable)
   - Identify files likely to be modified
   - Check existing patterns and conventions
   - Note dependencies and prerequisites

3. **Generate PRP**
   Create a PRP document with:
   - Clear summary and problem statement
   - Specific, measurable goals
   - Technical approach with file list
   - Acceptance criteria
   - Validation checklist

4. **Save Document**
   - Save to `.claude/prp/[task-name].md`
   - Or display inline if user prefers

## Arguments

- `[description]` - Natural language description of the task
- `--output <path>` - Custom output path for PRP file
- `--inline` - Display PRP inline instead of saving to file

## Example Usage

```
/harness:prp Add user authentication with JWT tokens

/harness:prp --inline Fix the race condition in the cache invalidation
```

## Example Output

```markdown
---
title: "User Authentication with JWT"
type: "feature"
priority: "high"
estimated_complexity: "large"
---

# Product Requirement Prompt (PRP)

## Summary

Implement user authentication using JSON Web Tokens (JWT) for secure API access.

## Problem Statement

The API currently has no authentication, allowing unrestricted access to all endpoints. We need secure user authentication to protect sensitive resources.

## Goals

- [ ] Implement JWT token generation on login
- [ ] Add token verification middleware
- [ ] Protect sensitive API endpoints
- [ ] Add token refresh mechanism

## Non-Goals

- OAuth/social login (future enhancement)
- Role-based access control (separate task)

## Technical Approach

### Proposed Solution

Use jsonwebtoken library for JWT operations. Add middleware to verify tokens on protected routes. Store refresh tokens in database.

### Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `src/auth/jwt.ts` | Create | JWT utilities |
| `src/middleware/auth.ts` | Create | Auth middleware |
| `src/routes/auth.ts` | Create | Login/logout routes |
| `src/routes/api.ts` | Modify | Add auth middleware |

...
```

## Template Location

`shared/templates/PRP-template.md`

## Related Commands

- `/harness:complete` - Complete the PRP task
- `/harness:validate` - Validate implementation


## When to Use This Skill

Claude Code command: harness:prp