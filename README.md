# HarnessSync — Claude Code → All Harnesses Total Sync

**Claude Code를 쓰면, 나머지는 알아서 따라온다.**

Claude Code의 설정(rules, skills, agents, commands, MCP, settings)을 OpenAI Codex, Gemini CLI, OpenCode에 **자동으로** 동기화하는 도구.

## 아키텍처

```
         ┌──────────────────┐
         │   Claude Code    │  ← Single Source of Truth
         │   ~/.claude/     │
         └────────┬─────────┘
                  │
         ┌────────┴─────────┐
         │   HarnessSync    │  ← Auto-triggered
         └──┬─────┬─────┬───┘
            │     │     │
     ┌──────┘     │     └──────┐
     ▼            ▼            ▼
┌─────────┐ ┌─────────┐ ┌──────────┐
│  Codex  │ │ Gemini  │ │ OpenCode │
│ ~/.codex│ │~/.gemini│ │~/.config/│
│         │ │         │ │ opencode │
└─────────┘ └─────────┘ └──────────┘
```

## 동기화 매핑

| Claude Code | → Codex | → Gemini CLI | → OpenCode |
|---|---|---|---|
| `CLAUDE.md` (rules) | `AGENTS.md` | `GEMINI.md` | `AGENTS.md` |
| `.claude/skills/` | `.codex/skills/` (symlink) | `GEMINI.md`에 인라인 | `.opencode/skills/` (symlink) |
| `.claude/agents/` | `skills/agent-{name}/` (변환) | `GEMINI.md`에 인라인 | `.opencode/agents/` (symlink) |
| `.claude/commands/` | `skills/cmd-{name}/` (변환) | `GEMINI.md`에 요약 | `.opencode/commands/` (symlink) |
| `.mcp.json` | `config.toml [mcp_servers]` | `settings.json` | `opencode.json` |
| `settings.json` (env) | `config.toml [env]` | `.gemini/.env` | `opencode.json [env]` |

### 스코프 지원

| 스코프 | Claude Code | → Codex | → Gemini | → OpenCode |
|---|---|---|---|---|
| **User** (전역) | `~/.claude/` | `~/.codex/` | `~/.gemini/` | `~/.config/opencode/` |
| **Project** (프로젝트) | `.claude/`, `CLAUDE.md` | `.codex/`, `AGENTS.md` | `GEMINI.md` | `.opencode/`, `AGENTS.md` |

## 자동 동기화 트리거 (3중)

1. **Shell wrapper** — `codex`, `gemini`, `opencode` 실행 시 자동 sync (5분 cooldown)
2. **Claude Code hook** — Claude Code가 설정 파일 수정 시 `PostToolUse` 훅으로 즉시 sync
3. **Watch mode** — `harnesssync watch`로 실시간 파일 감시 (fswatch/inotify)

→ 당신은 **Claude Code만 신경쓰면** 됩니다.

## 설치

```bash
# 1. 다운로드 (또는 직접 복사)
cp -r HarnessSync ~/.harnesssync

# 2. 설치
bash ~/.harnesssync/install.sh

# 3. 쉘 재시작
source ~/.zshrc   # or ~/.bashrc
```

## 사용법

```bash
# 기본: 아무것도 안 해도 됨
# codex, gemini, opencode 실행하면 자동 sync

# 수동 sync
harnesssync                    # 기본 (user + project)
harnesssync sync user          # 전역만
harnesssync sync project       # 현재 프로젝트만

# 실시간 감시 모드
harnesssync watch              # fswatch/inotify 기반

# 상태 확인
harnesssync status

# 강제 sync (cooldown 무시)
harnesssync force

# Dry run (변경 없이 미리보기)
python3 ~/.harnesssync/harnesssync-sync.py --dry-run --verbose
```

## macOS 백그라운드 데몬 (선택)

```bash
# launchd로 항상 watch 모드 실행
cp com.harnesssync.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.harnesssync.sync.plist

# 상태 확인
launchctl list | grep harnesssync

# 중지
launchctl unload ~/Library/LaunchAgents/com.harnesssync.sync.plist
```

## 주요 설계 결정

### Skills → Symlink (Codex, OpenCode)
플러그인 캐시를 직접 가리키는 symlink을 사용. `/plugin update` 하면 **re-sync 없이 즉시 반영**.

### Skills → Inline (Gemini)
Gemini CLI는 skills 시스템이 없으므로 GEMINI.md에 직접 삽입. `@import` 문법도 지원하지만, 단일 파일이 더 안정적.

### Agents → Conversion (Codex)
Codex에는 subagent 시스템이 없으므로, agent 정의를 `SKILL.md` 포맷으로 변환하여 skill로 등록.

### OpenCode 호환성
OpenCode는 이미 `~/.claude/CLAUDE.md`와 `~/.claude/skills/`를 폴백으로 읽지만, 명시적으로 `.opencode/` 경로에 symlink을 만들어 우선순위를 확보.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `HARNESSSYNC_HOME` | `~/.harnesssync` | HarnessSync 설치 경로 |
| `HARNESSSYNC_COOLDOWN` | `300` | 자동 sync 간격 (초) |
| `HARNESSSYNC_VERBOSE` | `0` | 자동 sync 시 출력 표시 |
| `CODEX_HOME` | `~/.codex` | Codex 홈 디렉토리 |

## 문제 해결

### "No paths to watch" 에러
→ `~/.claude/` 디렉토리가 존재하는지 확인. Claude Code를 한번이라도 실행해야 생성됨.

### Gemini에서 skills가 안 보임
→ Gemini CLI는 skills 시스템이 없으므로 GEMINI.md에 인라인됨. `/memory show`로 확인.

### OpenCode에서 이미 Claude Code 호환 모드가 있는데?
→ 맞음. 하지만 명시적 `.opencode/` 경로가 fallback보다 우선순위가 높고, MCP/settings는 별도 변환이 필요.

### Codex에서 symlink이 안 읽힘
→ Codex는 symlink을 공식 지원함. `.codex/skills/`와 `.agents/skills/` 모두에 symlink 생성.
