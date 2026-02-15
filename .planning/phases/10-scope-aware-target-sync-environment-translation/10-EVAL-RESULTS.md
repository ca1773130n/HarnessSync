# Phase 10 Evaluation Results

**Executed:** 2026-02-15
**Executor:** Claude (grd-executor)

## Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Module imports | PASS | All modules import OK | env_translator, adapters, orchestrator |
| S2: Function signatures | PASS | All 4 functions verified | translate, preserve, detect, check |
| S3: Env var pattern matching | PASS | ${VAR} and ${VAR:-default} | 13 inline assertions |
| S4: Transport type detection | PASS | stdio/sse/http/unknown | All 4 types correct |
| S5: Transport support validation | PASS | SSE rejected on Codex | Warning message includes transport |
| S6: Adapter interface compatibility | PASS | sync_mcp + sync_mcp_scoped | Backward compat preserved |

**Sanity gate: 6/6 PASSED**

## Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Codex scope routing | 3 user + 1 proj | 3 user + 1 proj | MET | api, port, plugin -> user; project-db -> project |
| P2: Gemini scope routing | 4 user + 1 proj | 4 user + 1 proj | MET | api, port, plugin, sse -> user; project-db -> project |
| P3: Plugin MCPs user-scope | Not in project | Not in project | MET | Verified on both Codex and Gemini |
| P4: Codex env translation | 100% literal | 100% literal | MET | sk-test-integration-key resolved, 3000 default used |
| P5: Gemini env preservation | 100% syntax | 100% syntax | MET | ${TEST_API_KEY} and ${UNDEFINED_PORT:-3000} preserved |
| P6: Transport validation | SSE skipped + warning | SSE skipped + warning | MET | Codex and OpenCode skip; Gemini includes |

**Proxy metrics: 6/6 MET**

## Integration Test Results

`python verify_phase10_integration.py` — **30/30 checks passed**

- SYNC-01 (Gemini scope): 4/4
- SYNC-02 (Codex scope): 7/7
- SYNC-03 (Plugin user-scope): 4/4
- SYNC-04 (Transport detection): 5/5
- ENV-01 (${VAR} translation): 3/3
- ENV-02 (${VAR:-default}): 2/2
- ENV-03 (Gemini preservation): 2/2
- OpenCode transport: 3/3

## Deferred Status

| ID | Metric | Status | Validates At | Risk |
|----|--------|--------|-------------|------|
| DEFER-10-01 | Real Codex CLI integration | PENDING | Post-phase | TOML syntax errors |
| DEFER-10-02 | Real Gemini CLI integration | PENDING | Post-phase | JSON structure errors |
| DEFER-10-03 | Full v2.0 pipeline | PENDING | Phase 11 | Scope collapse, env gaps |
