# Phase 7: Packaging & Distribution - Research

**Researched:** 2026-02-15
**Domain:** Claude Code Plugin Packaging, Marketplace Distribution, Cross-Platform Installation
**Confidence:** HIGH

## Summary

Phase 7 prepares HarnessSync for public distribution via the Claude Code plugin marketplace. The phase involves three critical areas: (1) **plugin validation** using `claude plugin validate` to ensure directory structure compliance and correct plugin.json schema, (2) **marketplace.json creation** with absolute GitHub URLs for distribution and proper metadata, and (3) **cross-platform installation testing** on macOS (native), Linux (native), and Windows (WSL2/native) with junction fallback for symlinks. The install.sh script must detect shell type (bash/zsh), create target directories (~/.codex/, ~/.gemini/, ~/.opencode/), and configure shell integration.

**Primary recommendation:** Use GitHub Actions matrix workflows (ubuntu-latest, macos-latest, windows-latest) to automate validation and installation testing. Create marketplace.json with `source: github` pointing to the repository. Test `claude plugin validate`, marketplace installation via `/plugin marketplace add`, and GitHub installation via `/plugin install github:username/HarnessSync`. Validate install.sh behavior across all three platforms before public release.

## User Constraints (No CONTEXT.md provided)

### Locked Decisions (from STATE.md and prior phases)
1. **Python 3 stdlib only** — Zero dependency footprint (Decision #1)
2. **Plugin manifest declares future structure** — plugin.json includes hooks/commands/mcp even if some scripts don't exist yet (Decision #16)
3. **install.sh already exists** — Must be enhanced for cross-platform directory creation and shell detection, not built from scratch
4. **3-tier symlink fallback** — Native symlink → junction (Windows dirs) → copy with marker (Decision #7)
5. **Zero external dependencies** — install.sh cannot use npm, pip, or any package managers for runtime dependencies

### Claude's Discretion
1. **marketplace.json structure** — How to organize plugin metadata, whether to use `strict: false` or keep plugin.json
2. **GitHub Actions workflow design** — Which test matrices, how to validate across platforms
3. **Documentation strategy** — Whether to create separate INSTALLATION.md, update README.md, or both
4. **Versioning scheme** — Whether to start at 1.0.0 or use pre-release tags (0.9.0-beta)
5. **Installation test automation** — Level of automation for cross-platform testing
6. **Marketplace naming** — Whether to create custom marketplace or submit to official Anthropic marketplace

### Deferred Ideas (OUT OF SCOPE for Phase 7)
1. **npm/pip package distribution** — Only Claude Code plugin marketplace, not npm or PyPI
2. **Automated version bumping in CI** — Manual version management is sufficient
3. **Homebrew/apt package managers** — Plugin-only distribution
4. **Windows native installer** — Only script-based installation via install.sh
5. **Plugin auto-update mechanism** — Claude Code handles updates via marketplace

---

## Paper-Backed Recommendations

Phase 7 is an engineering/distribution phase without deep research literature, but best practices are derived from official Claude Code documentation and community experience.

### Recommendation 1: Use GitHub Actions Matrix for Cross-Platform Validation

**Recommendation:** Implement GitHub Actions workflow with matrix strategy testing ubuntu-latest, macos-latest, and windows-latest runners.

**Evidence:**
- [GitHub Actions matrix workflows](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners) — Matrix workflows can simultaneously test across multiple operating systems and versions
- [Multi-platform testing with GitHub Actions](https://levelup.gitconnected.com/utilizing-github-actions-to-build-and-test-on-multiple-platforms-a7fe3aa6ce2a) (2024) — Practical examples showing bash compatibility across Linux, macOS, and Windows (with git-bash)
- [Claude Code plugin validation](https://code.claude.com/docs/en/plugins-reference) — Official documentation recommends `claude plugin validate` in CI/CD workflows

**Confidence:** HIGH — GitHub Actions is the standard CI/CD platform for open-source projects in 2026, with official GitHub-hosted runners for all target platforms.

**Expected improvement:** Automated validation catches directory structure errors, missing files, and platform-specific installation issues before users encounter them.

**Caveats:** Windows runner requires Git Bash or WSL for bash script execution. Windows-latest runner has WSL2 pre-installed (2026), but native Windows testing requires special handling.

### Recommendation 2: Create marketplace.json with GitHub Source

**Recommendation:** Use `source: { "source": "github", "repo": "username/HarnessSync" }` in marketplace.json for distribution.

**Evidence:**
- [Claude Code marketplace.json specification](https://code.claude.com/docs/en/plugin-marketplaces) — GitHub source is recommended over relative paths for public distribution: "Relative paths only work when users add your marketplace via Git. For URL-based distribution, use GitHub, npm, or git URL sources instead."
- [Plugin sources documentation](https://code.claude.com/docs/en/plugin-marketplaces#plugin-sources) — GitHub sources support pinning to specific `ref` (branch/tag) or `sha` (commit hash) for versioning
- [Marketplace schema](https://code.claude.com/docs/en/plugin-marketplaces#marketplace-schema) — Required fields: `name`, `owner`, `plugins` array with `name` and `source`

**Confidence:** HIGH — Official documentation explicitly recommends GitHub source for public plugins.

**Expected improvement:** Users can install directly via `/plugin install HarnessSync@marketplace-name` or `/plugin install github:username/HarnessSync` without manual git clone.

**Caveats:** Private repositories require `GITHUB_TOKEN` environment variable for background auto-updates. Public repositories have no authentication restrictions.

### Recommendation 3: Test Windows Junction Fallback for Symlinks

**Recommendation:** Install.sh must detect Windows environment and use junction points for directory symlinks instead of native symlinks requiring admin privileges.

**Evidence:**
- [Windows symlinks vs junctions for WSL2](https://blog.trailofbits.com/2024/02/12/why-windows-cant-follow-wsl-symlinks/) — "Windows handles only symlinks that were created by Windows, using its standard tags. WSL symlinks of the 'LX symlink' type fail."
- [WSL2 symlink best practices 2026](https://www.mslinn.com/wsl/9000-wsl-volumes.html) — "Junctions are more desirable than Linux hard links and symlinks because junctions are visible in Windows and also in WSL. Junctions are permitted within a single NTFS volume, or between two NTFS volumes."
- Project Decision #7 (STATE.md) — "3-tier symlink fallback: Native symlink → junction (Windows dirs) → copy with marker"

**Confidence:** HIGH — Windows junction points are the correct cross-platform solution for directory symlinks.

**Expected improvement:** HarnessSync installs on Windows without requiring "Run as Administrator", improving accessibility.

**Caveats:** Junctions work only for directories, not files. File symlinks require copy fallback on Windows. WSL2 Linux filesystem (`/home/`) uses native symlinks, but Windows filesystem (`/mnt/c/`) requires junctions.

### Recommendation 4: Validate plugin.json Schema Before Distribution

**Recommendation:** Run `claude plugin validate .` in CI and pre-commit hooks to catch manifest errors early.

**Evidence:**
- [Claude plugin validate command](https://code.claude.com/docs/en/plugins-reference) — "Validate your marketplace JSON syntax: `claude plugin validate .` or from within Claude Code: `/plugin validate .`"
- [Plugin structure requirements](https://code.claude.com/docs/en/plugins-reference#plugin-directory-structure) — "Components must be at the plugin root, not inside `.claude-plugin/`. Only plugin.json belongs in `.claude-plugin/`."
- [Common validation errors](https://code.claude.com/docs/en/plugins-reference#debugging-and-development-tools) — Typical errors include missing required fields, invalid JSON syntax, duplicate plugin names, and incorrect directory structure

**Confidence:** HIGH — Official validation tool catches all schema and structure errors before distribution.

**Expected improvement:** Users never encounter installation failures due to malformed plugin.json or incorrect directory structure.

**Caveats:** Validation only checks manifest and structure, not runtime behavior (MCP server startup, hook execution, etc.). Runtime testing still required.

---

## Standard Stack

### Core Tools

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| `claude` CLI | Latest | Plugin validation, local testing | Official Claude Code CLI, required for `claude plugin validate` |
| Bash | 5.x+ | install.sh script, shell integration | Standard on Linux, available via Homebrew on macOS, Git Bash on Windows |
| Python | 3.10+ | Runtime dependency for HarnessSync | Already required by Phase 1-6, stdlib-only constraint |
| Git | 2.x+ | Version control, marketplace distribution | Universal version control, required for GitHub-based distribution |

### Supporting Tools

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| GitHub Actions | N/A | CI/CD for automated validation | Recommended for all public plugins |
| `jq` | 1.6+ | JSON validation in bash scripts | Optional: install.sh can validate plugin.json before installation |
| `sed`/`awk` | Standard | Text processing in install.sh | Shell integration setup, bashrc/zshrc modification |
| `realpath` | Standard | Resolve symlink targets | Validation scripts, installation path resolution |

### Development Dependencies

| Tool | Purpose | Notes |
|------|---------|-------|
| `yamllint` | Validate GitHub Actions YAML | Development-time only |
| `shellcheck` | Bash script linting | Catch install.sh errors before testing |
| `act` | Local GitHub Actions testing | Test workflows locally before pushing |

### Installation

```bash
# Core (already installed on development machines)
claude --version    # Claude Code CLI
bash --version      # Bash 5.x+ (macOS: brew install bash)
python3 --version   # Python 3.10+
git --version       # Git 2.x+

# Optional: Install.sh validation tools
brew install jq shellcheck  # macOS
sudo apt-get install jq shellcheck  # Ubuntu/Debian

# Optional: Local GitHub Actions testing
brew install act  # macOS
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash  # Linux
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Recommendation |
|------------|-----------|----------|----------------|
| GitHub Actions | GitLab CI / CircleCI | GitLab CI has similar matrix testing, but GitHub is standard for open-source plugins | Use GitHub Actions (ecosystem standard) |
| Bash install.sh | Python setup.py / npm install script | Python/npm adds runtime dependency, bash is universal | Keep bash (zero-dependency constraint) |
| GitHub source | npm package source | npm distribution requires Node.js runtime, adds complexity | Use GitHub (simpler, no runtime) |
| marketplace.json | Direct plugin.json distribution | marketplace.json enables centralized discovery and versioning | Use marketplace.json (standard pattern) |
| Manual testing | Automated test suite | Full automation requires significant infrastructure | Hybrid: Automate validation, manual test critical paths |

---

## Architecture Patterns

### Pattern 1: Marketplace Structure (Official Pattern)

**What:** Standard Claude Code plugin marketplace with `.claude-plugin/marketplace.json` at repository root.

**When to use:** Always, for public plugin distribution.

**Documentation reference:** [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)

**Example structure:**
```
HarnessSync/
├── .claude-plugin/
│   ├── plugin.json          # Plugin manifest
│   └── marketplace.json     # Marketplace catalog
├── commands/                 # Slash commands
│   ├── sync.md
│   └── sync-status.md
├── hooks/                    # Hook definitions
│   └── hooks.json
├── src/                      # Python sync engine
│   ├── adapters/
│   ├── commands/
│   ├── mcp/
│   └── utils/
├── install.sh               # Installation script
├── README.md                # User documentation
├── LICENSE                  # MIT license
└── .github/
    └── workflows/
        └── validate.yml     # CI/CD validation
```

**marketplace.json example:**
```json
{
  "name": "harness-sync",
  "owner": {
    "name": "HarnessSync Contributors",
    "email": "contact@example.com"
  },
  "metadata": {
    "description": "Sync Claude Code configuration to Codex, Gemini CLI, and OpenCode",
    "version": "1.0.0"
  },
  "plugins": [
    {
      "name": "HarnessSync",
      "source": {
        "source": "github",
        "repo": "username/HarnessSync"
      },
      "description": "Configure once, sync everywhere. Automatic config sync across AI coding harnesses.",
      "version": "1.0.0",
      "author": {
        "name": "HarnessSync Contributors"
      },
      "homepage": "https://github.com/username/HarnessSync",
      "repository": "https://github.com/username/HarnessSync",
      "license": "MIT",
      "keywords": ["sync", "codex", "gemini", "opencode", "configuration"],
      "category": "productivity"
    }
  ]
}
```

### Pattern 2: GitHub Actions Matrix Workflow

**What:** Multi-platform CI workflow testing plugin validation and installation across macOS, Linux, and Windows.

**When to use:** Always, for automated pre-release validation.

**Example workflow:**
```yaml
name: Validate Plugin
on: [push, pull_request]

jobs:
  validate:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Validate plugin structure
        run: |
          # Check required directories exist
          test -d .claude-plugin || exit 1
          test -f .claude-plugin/plugin.json || exit 1
          test -d commands || exit 1
          test -d hooks || exit 1
          test -d src || exit 1

      - name: Validate plugin.json syntax
        run: |
          # Use jq to validate JSON
          jq empty .claude-plugin/plugin.json

      - name: Validate marketplace.json
        run: |
          test -f .claude-plugin/marketplace.json || exit 1
          jq empty .claude-plugin/marketplace.json

      - name: Test install.sh (Unix)
        if: runner.os != 'Windows'
        run: |
          bash install.sh --dry-run

      - name: Test install.sh (Windows with WSL)
        if: runner.os == 'Windows'
        run: |
          wsl bash install.sh --dry-run

      - name: Lint shell scripts
        if: runner.os == 'Linux'
        run: |
          shellcheck install.sh || true
```

**Rationale:** GitHub Actions runners have pre-installed Python, Git, and bash (via Git Bash on Windows). Matrix strategy runs all tests in parallel, catching platform-specific issues.

### Pattern 3: Install.sh Shell Detection and Integration

**What:** Detect user's shell (bash/zsh) and add source line to appropriate rc file.

**When to use:** Always, for automatic shell integration setup.

**Reference:** [Shell Integration Best Practices 2026](https://mac.install.guide/terminal/configuration)

**Example implementation:**
```bash
#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect shell
if [[ -n "${ZSH_VERSION:-}" ]] || [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ -n "${BASH_VERSION:-}" ]] || [[ "$SHELL" == *"bash"* ]]; then
    SHELL_RC="$HOME/.bashrc"
else
    echo "Warning: Could not detect shell. Add manually:"
    echo "  source \"$PLUGIN_ROOT/shell-integration.sh\""
    exit 0
fi

# Add shell integration if not already present
if ! grep -q "HarnessSync" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# HarnessSync: Auto-sync Claude Code config" >> "$SHELL_RC"
    echo "source \"$PLUGIN_ROOT/shell-integration.sh\"" >> "$SHELL_RC"
    echo "✓ Added to $SHELL_RC"
else
    echo "✓ Already in $SHELL_RC"
fi
```

**Rationale:** Modern macOS defaults to zsh (since Catalina), Linux typically uses bash. Detecting via `$SHELL` and `$ZSH_VERSION`/`$BASH_VERSION` covers both cases. Idempotent checks (`grep -q`) prevent duplicate entries.

### Pattern 4: Cross-Platform Directory Creation

**What:** Create target directories (~/.codex/, ~/.gemini/, ~/.opencode/) with proper permissions.

**When to use:** Always, in install.sh before any symlink operations.

**Example implementation:**
```bash
#!/usr/bin/env bash

echo "[1/3] Creating target directories..."

# Codex
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "${CODEX_HOME:-$HOME/.codex}/.agents/skills"

# Gemini
mkdir -p "$HOME/.gemini"

# OpenCode
mkdir -p "$HOME/.config/opencode/skills"
mkdir -p "$HOME/.config/opencode/agents"
mkdir -p "$HOME/.config/opencode/commands"

echo "✓ Target directories created"
```

**Rationale:** `mkdir -p` is idempotent (won't fail if directory exists) and creates parent directories. OpenCode uses XDG Base Directory specification (~/.config/), others use home directory.

### Anti-Patterns to Avoid

- **Hardcoding plugin paths:** Use `${CLAUDE_PLUGIN_ROOT}` in hooks, MCP configs, and commands to support installation in arbitrary locations.
- **Assuming admin privileges on Windows:** Symlinks require admin on Windows; use junctions for directories, copy for files.
- **Relative paths in marketplace.json:** GitHub source uses absolute repo references, not relative paths.
- **Skipping validation in CI:** `claude plugin validate` catches errors before users encounter them.
- **Manual version management:** Maintain single source of truth (plugin.json) for version, reference in marketplace.json.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Plugin validation | Custom JSON schema validator | `claude plugin validate` CLI | Official tool catches all structure errors, validates against current schema |
| Cross-platform symlinks | Custom symlink library | OS-specific logic (ln -s / mklink / junction) | Platform symlink APIs are complex; use simple if/elif based on `$OSTYPE` |
| Shell RC file modification | Manual string concatenation | grep + append pattern | Prevents duplicate entries, handles missing files gracefully |
| GitHub Actions runners | Self-hosted runners | GitHub-hosted runners | Pre-configured with Python, Git, bash; zero maintenance |
| Marketplace JSON schema | Hand-written schema | Official marketplace.json examples | Schema evolves with Claude Code updates |

**Key insight:** Plugin packaging is well-documented by Anthropic. Follow official patterns instead of inventing custom solutions.

---

## Common Pitfalls

### Pitfall 1: Components in .claude-plugin/ Instead of Root

**What goes wrong:** Developers place commands/, hooks/, agents/ inside `.claude-plugin/` directory. Claude Code fails to discover these components. Plugin installs successfully but all features are missing.

**Why it happens:** Misunderstanding plugin directory structure. Visual Studio Code extensions use similar nested structure, causing confusion.

**How to avoid:**
- Follow strict structure: Only `plugin.json` and `marketplace.json` go in `.claude-plugin/`
- All other directories (commands/, hooks/, skills/, agents/, src/) at plugin root
- Run `claude plugin validate .` in CI to catch structure errors
- Test plugin installation locally before public release

**Warning signs:**
- `/sync` command not found after installation
- Hooks don't fire on PostToolUse events
- MCP servers listed in plugin.json but not starting

**Documentation reference:** [Plugin directory structure](https://code.claude.com/docs/en/plugins-reference#plugin-directory-structure)

### Pitfall 2: Relative Paths in marketplace.json for Public Distribution

**What goes wrong:** marketplace.json uses `"source": "./plugins/HarnessSync"` for plugin path. Works when users clone repository but fails when users add marketplace via URL (`/plugin marketplace add https://example.com/marketplace.json`).

**Why it happens:** Documentation shows relative path examples for monorepo scenarios. Developers copy examples without understanding URL-based limitation.

**How to avoid:**
- Use GitHub source for public plugins: `{"source": "github", "repo": "username/HarnessSync"}`
- Reserve relative paths for private monorepos distributed via Git clone
- Test installation via URL: `/plugin marketplace add https://raw.githubusercontent.com/.../marketplace.json`
- Document installation methods in README (GitHub install vs marketplace URL)

**Warning signs:**
- "Path not found" errors when installing from marketplace URL
- Plugin installs fine with `/plugin marketplace add github:username/repo` but fails with URL
- Relative path resolution errors in logs

**Documentation reference:** [Plugins with relative paths fail in URL-based marketplaces](https://code.claude.com/docs/en/plugin-marketplaces#plugins-with-relative-paths-fail-in-url-based-marketplaces)

### Pitfall 3: Windows Symlink Failures (Admin Privilege Required)

**What goes wrong:** install.sh uses `ln -s` on Windows. Fails with "Operation not permitted" unless user runs as Administrator. Users without admin access cannot install plugin.

**Why it happens:** Windows treats symlinks as security risk (requires `SeCreateSymbolicLinkPrivilege`). Native `ln -s` creates NTFS symlinks requiring admin, not junctions.

**How to avoid:**
- Detect Windows environment: `if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then`
- Use junction for directories: `cmd //c mklink //J "target" "source"` (no admin required)
- Use copy for files: `cp "source" "target"` with `.harnesssync-copied` marker
- Test on Windows without admin: GitHub Actions windows-latest runner runs as non-admin
- Document Windows requirements: "WSL2 recommended, native Windows uses junction fallback"

**Warning signs:**
- Installation succeeds on macOS/Linux but fails on Windows
- "You do not have sufficient privilege" errors
- Symlinks appear broken in Windows Explorer but work in WSL

**Documentation reference:** Project Decision #7 (STATE.md), [Windows symlink issues](https://blog.trailofbits.com/2024/02/12/why-windows-cant-follow-wsl-symlinks/)

### Pitfall 4: Missing plugin.json Validation Before Distribution

**What goes wrong:** Developer pushes plugin with typo in plugin.json (`"comands"` instead of `"commands"`). Users install plugin but commands don't load. Developer receives bug reports but can't reproduce locally.

**Why it happens:** No pre-commit validation. Developer tests with `/plugin install ./local-path` which may have different loading behavior than marketplace installation.

**How to avoid:**
- Add pre-commit hook: `git add .git/hooks/pre-commit` with `claude plugin validate . || exit 1`
- Run validation in GitHub Actions on every push
- Test marketplace installation flow before tagging release: `/plugin marketplace add ./`, `/plugin install HarnessSync@marketplace-name`
- Use `jq` to validate JSON syntax: `jq empty .claude-plugin/plugin.json`

**Warning signs:**
- Plugin validates locally but fails after installation from marketplace
- "Invalid manifest" errors in Claude Code logs
- Components missing after installation but present in repository

**Documentation reference:** [Validation and testing](https://code.claude.com/docs/en/plugin-marketplaces#validation-and-testing)

### Pitfall 5: Shell Integration Not Idempotent

**What goes wrong:** Running install.sh multiple times adds duplicate `source ~/.harnesssync/shell-integration.sh` lines to .bashrc/.zshrc. User's shell startup becomes slow, source errors appear.

**Why it happens:** install.sh appends to rc file without checking if line already exists.

**How to avoid:**
- Check before append: `if ! grep -q "HarnessSync" "$SHELL_RC"; then ... fi`
- Use unique marker comments: `# HarnessSync: Auto-sync`
- Make entire install.sh idempotent (safe to run multiple times)
- Document re-installation process: "Safe to re-run install.sh"

**Warning signs:**
- Slow shell startup after multiple installs
- Duplicate "HarnessSync loaded" messages
- ~/.bashrc contains multiple identical source lines

**Best practice reference:** [Shell Integration - NVM](https://deepwiki.com/nvm-sh/nvm/3.2-shell-integration)

### Pitfall 6: Forgetting CLAUDE_PLUGIN_ROOT in Hooks/MCP

**What goes wrong:** Hook configuration hardcodes path: `"command": "/Users/dev/.claude/plugins/HarnessSync/hooks/post-tool.py"`. Works on developer's machine but fails for all users with different install paths.

**Why it happens:** Copy-paste from local testing without parameterizing paths.

**How to avoid:**
- Always use `${CLAUDE_PLUGIN_ROOT}` variable: `"command": "${CLAUDE_PLUGIN_ROOT}/hooks/post-tool.py"`
- Test with non-standard install path: `/tmp/test-plugin`
- Validate all file references in plugin.json, hooks.json, .mcp.json
- Document environment variables in README

**Warning signs:**
- Plugin works in development but fails after marketplace installation
- "File not found" errors in hook execution logs
- MCP servers fail to start with path errors

**Documentation reference:** [Environment variables](https://code.claude.com/docs/en/plugins-reference#environment-variables)

### Pitfall 7: No Cross-Platform Testing Before Release

**What goes wrong:** Developer tests only on macOS. Ships plugin. Windows users report installation failures (symlink errors), Linux users report bash compatibility issues (bashisms in install.sh).

**Why it happens:** Lack of automated cross-platform CI. Manual testing on all platforms is time-consuming.

**How to avoid:**
- Set up GitHub Actions matrix with all three platforms (ubuntu-latest, macos-latest, windows-latest)
- Test install.sh on Windows with Git Bash and WSL2
- Use shellcheck to catch bash compatibility issues
- Document platform requirements in README: "Tested on macOS 13+, Ubuntu 22.04+, Windows 11 with WSL2"

**Warning signs:**
- Bug reports from specific OS users only
- Bash syntax errors on specific platforms
- Features work on development OS but fail elsewhere

**Best practice reference:** [GitHub Actions matrix testing](https://levelup.gitconnected.com/utilizing-github-actions-to-build-and-test-on-multiple-platforms-a7fe3aa6ce2a)

---

## Verification Strategy

### Recommended Verification Tiers for Phase 7

Phase 7 success criteria from objective:

1. Plugin passes `claude plugin validate` with no errors
2. Plugin published to Claude Code marketplace with marketplace.json
3. Plugin installable from GitHub via `/plugin install github:username/HarnessSync`
4. install.sh creates target directories, detects shell, configures integration
5. Installation testing succeeds on macOS (native), Linux (native), Windows (WSL2, native with junction)

| Item | Recommended Tier | Rationale |
|------|------------------|-----------|
| plugin.json schema validation | Level 1 (Sanity) | `claude plugin validate` runs instantly, catches all schema errors |
| Directory structure correctness | Level 1 (Sanity) | Simple file existence checks (`test -d commands`, `test -f plugin.json`) |
| marketplace.json syntax validation | Level 1 (Sanity) | `jq empty marketplace.json` validates JSON syntax immediately |
| GitHub Actions workflow runs | Level 2 (Proxy) | CI passes = high confidence in cross-platform compatibility |
| install.sh on macOS (native) | Level 2 (Proxy) | Can test immediately on development machine |
| install.sh on Linux (Ubuntu 22.04) | Level 2 (Proxy) | GitHub Actions runner or local Docker container |
| GitHub installation works | Level 2 (Proxy) | `/plugin install github:username/HarnessSync` in test repo |
| install.sh on Windows WSL2 | Level 3 (Deferred) | Requires Windows machine or cloud VM |
| install.sh on Windows native | Level 3 (Deferred) | Requires Windows with Git Bash, junction testing |
| Marketplace URL installation | Level 3 (Deferred) | Requires public marketplace.json hosted on GitHub Pages or raw.githubusercontent.com |
| Integration with real Codex/Gemini/OpenCode | Level 3 (Deferred) | Requires all three CLIs installed (covered by Phase 3 deferred validations) |

**Level 1 checks to always include:**
1. Run `claude plugin validate .` and verify exit code 0
2. Check `.claude-plugin/plugin.json` exists and parses as valid JSON
3. Check `.claude-plugin/marketplace.json` exists and parses as valid JSON
4. Verify `commands/`, `hooks/`, `src/` directories exist at root (not in `.claude-plugin/`)
5. Confirm `install.sh` is executable (`test -x install.sh`)

**Level 2 proxy metrics:**
1. GitHub Actions workflow passes on all three platforms (ubuntu-latest, macos-latest, windows-latest)
2. install.sh completes without errors on macOS development machine
3. install.sh dry-run succeeds in Linux Docker container
4. `/plugin install github:username/HarnessSync` succeeds in test repository
5. plugin.json references correct file paths (commands/sync.md, hooks/hooks.json, src/mcp/server.py)

**Level 3 deferred items:**
1. Windows native testing with junction fallback validation
2. Windows WSL2 testing with native symlink validation
3. Marketplace URL installation from raw.githubusercontent.com
4. End-to-end sync testing with Codex/Gemini/OpenCode installed (Phase 3 validations)
5. Plugin update workflow (`/plugin update HarnessSync@marketplace`) with version bumps

---

## Production Considerations

Phase 7 is the public release phase. Production considerations focus on user experience, error handling, and documentation.

### Known Failure Modes

#### Failure Mode 1: plugin.json Schema Changes in Claude Code Updates

**Description:** Claude Code updates may introduce new required fields or deprecate existing fields in plugin.json schema. Plugins with outdated manifests fail validation.

**Prevention:**
- Pin Claude Code version in GitHub Actions for CI stability
- Subscribe to Claude Code changelog for breaking changes
- Use minimal plugin.json (only required fields + essential metadata)
- Test plugin with `claude --version` reporting tool

**Detection:**
- `claude plugin validate` starts failing after Claude Code update
- User reports of "invalid manifest" errors
- Marketplace installation failures with schema validation errors

#### Failure Mode 2: GitHub Repository Becomes Private/Deleted

**Description:** If repository is made private or deleted, all users with installed plugin lose access to updates. Marketplace installation fails with 404 errors.

**Prevention:**
- Document repository permanence policy in README
- Use GitHub Archive feature for long-term preservation
- Consider mirrors on GitLab/Bitbucket for redundancy
- Communicate deprecation plan if discontinuing plugin

**Detection:**
- Users report "repository not found" during `/plugin update`
- GitHub returns 404 for marketplace.json URL
- Installation from GitHub fails with authentication errors (if made private)

#### Failure Mode 3: install.sh Fails on Unsupported Platforms

**Description:** install.sh tested on macOS/Linux/Windows but fails on FreeBSD, older macOS versions, or custom Linux distributions. Users cannot complete installation.

**Prevention:**
- Document tested platforms in README (macOS 13+, Ubuntu 22.04+, Windows 11)
- Add OS detection with graceful degradation: `uname -s` check
- Provide manual installation instructions as fallback
- Test on oldest supported platform version

**Detection:**
- Bug reports from users on non-standard platforms
- Shell script errors on older bash versions (< 4.0)
- Missing utilities (`realpath`, `readlink`) on minimal distributions

### Scaling Concerns

#### Concern 1: Large Plugin Cache Growth

**Description:** Users with many plugins accumulate large cache directories (~/.claude/plugins/cache/). HarnessSync symlinks reduce duplication but don't eliminate it.

**At current scale:** Single-user installations, cache size <100MB.

**At production scale:** Enterprise deployments with 50+ plugins per user, cache size >1GB. Shared filesystems (NFS) may have inode limits.

**Mitigation:**
- Document cache cleanup: `/plugin uninstall` removes cache entries
- Consider hard links instead of copies for identical files across plugins
- Advise users to use project-scope plugins (`.claude/`) to avoid global cache bloat

#### Concern 2: Marketplace Availability and Rate Limiting

**Description:** Public marketplace hosted on GitHub Pages or raw.githubusercontent.com. High traffic may hit rate limits or cause availability issues.

**At current scale:** <100 installations/day, GitHub rate limits not a concern.

**At production scale:** >1000 installations/day, potential GitHub API rate limiting (5000 requests/hour for authenticated, 60/hour for unauthenticated).

**Mitigation:**
- Use GitHub Releases for distribution instead of raw.githubusercontent.com
- Implement CDN caching (Cloudflare Pages, Vercel) for marketplace.json
- Document GITHUB_TOKEN usage for authenticated requests (higher rate limits)

### Common Implementation Traps

#### Trap 1: Forgetting to Update marketplace.json Version

**What goes wrong:** Developer releases v1.1.0, updates plugin.json version but forgets to update marketplace.json. Users see v1.0.0 in marketplace listings.

**Correct approach:**
- Automate version sync: CI script that checks `jq -r '.version' plugin.json` == `jq -r '.metadata.version' marketplace.json`
- Use single-source-of-truth: marketplace.json references plugin.json version (not duplicated)
- Document release checklist in CONTRIBUTING.md

#### Trap 2: Testing Only with `/plugin install ./local-path`

**What goes wrong:** Local installation bypasses GitHub clone, marketplace resolution, and URL-based path handling. Bugs only appear after public release.

**Correct approach:**
- Test marketplace flow: `/plugin marketplace add ./`, `/plugin install HarnessSync@marketplace-name`
- Test GitHub flow: `/plugin install github:username/HarnessSync`
- Test URL flow: `/plugin marketplace add https://raw.githubusercontent.com/.../marketplace.json`
- Create separate test repository for pre-release validation

#### Trap 3: Assuming All Users Have Git Configured

**What goes wrong:** install.sh or plugin assumes `git` is in PATH and configured with user.name/user.email. Fails on clean machines or CI environments.

**Correct approach:**
- Check Git availability: `command -v git >/dev/null || { echo "Git required"; exit 1; }`
- Don't assume Git config: avoid `git config --global` in install scripts
- Document Git prerequisite in README

---

## Code Examples

### Example 1: Complete marketplace.json

```json
{
  "name": "harness-sync",
  "owner": {
    "name": "HarnessSync Contributors",
    "email": "harnesssync@example.com"
  },
  "metadata": {
    "description": "Sync Claude Code configuration to Codex, Gemini CLI, and OpenCode. Configure once, sync everywhere.",
    "version": "1.0.0"
  },
  "plugins": [
    {
      "name": "HarnessSync",
      "source": {
        "source": "github",
        "repo": "username/HarnessSync",
        "ref": "main"
      },
      "description": "Automatic config synchronization across AI coding harnesses",
      "version": "1.0.0",
      "author": {
        "name": "HarnessSync Contributors",
        "email": "harnesssync@example.com"
      },
      "homepage": "https://github.com/username/HarnessSync",
      "repository": "https://github.com/username/HarnessSync",
      "license": "MIT",
      "keywords": ["sync", "codex", "gemini", "opencode", "configuration", "automation"],
      "category": "productivity",
      "commands": {
        "sync": "commands/sync.md",
        "sync-status": "commands/sync-status.md"
      },
      "hooks": "hooks/hooks.json",
      "mcpServers": {
        "server": "src/mcp/server.py"
      }
    }
  ]
}
```

**Source:** [Claude Code marketplace.json specification](https://code.claude.com/docs/en/plugin-marketplaces#create-the-marketplace-file)

### Example 2: GitHub Actions Validation Workflow

```yaml
name: Validate Plugin Structure
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  validate:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ['3.10', '3.11', '3.12']

    runs-on: ${{ matrix.os }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Verify directory structure
        shell: bash
        run: |
          # Required directories at root
          test -d .claude-plugin || { echo "Missing .claude-plugin/"; exit 1; }
          test -d commands || { echo "Missing commands/"; exit 1; }
          test -d hooks || { echo "Missing hooks/"; exit 1; }
          test -d src || { echo "Missing src/"; exit 1; }

          # Required files
          test -f .claude-plugin/plugin.json || { echo "Missing plugin.json"; exit 1; }
          test -f .claude-plugin/marketplace.json || { echo "Missing marketplace.json"; exit 1; }
          test -f install.sh || { echo "Missing install.sh"; exit 1; }
          test -x install.sh || { echo "install.sh not executable"; exit 1; }

          echo "✓ Directory structure valid"

      - name: Validate JSON syntax
        shell: bash
        run: |
          # Requires jq (pre-installed on GitHub runners)
          jq empty .claude-plugin/plugin.json || { echo "Invalid plugin.json"; exit 1; }
          jq empty .claude-plugin/marketplace.json || { echo "Invalid marketplace.json"; exit 1; }
          echo "✓ JSON syntax valid"

      - name: Validate plugin.json schema
        shell: bash
        run: |
          # Check required fields
          jq -e '.name' .claude-plugin/plugin.json >/dev/null || { echo "Missing name field"; exit 1; }
          jq -e '.version' .claude-plugin/plugin.json >/dev/null || { echo "Missing version field"; exit 1; }
          echo "✓ plugin.json schema valid"

      - name: Validate version consistency
        shell: bash
        run: |
          PLUGIN_VERSION=$(jq -r '.version' .claude-plugin/plugin.json)
          MARKETPLACE_VERSION=$(jq -r '.plugins[0].version' .claude-plugin/marketplace.json)

          if [[ "$PLUGIN_VERSION" != "$MARKETPLACE_VERSION" ]]; then
            echo "Version mismatch: plugin.json=$PLUGIN_VERSION, marketplace.json=$MARKETPLACE_VERSION"
            exit 1
          fi

          echo "✓ Version consistency valid ($PLUGIN_VERSION)"

      - name: Test install.sh (Unix)
        if: runner.os != 'Windows'
        shell: bash
        run: |
          # Add --dry-run flag support to install.sh for testing
          bash install.sh --dry-run || { echo "install.sh failed"; exit 1; }
          echo "✓ install.sh succeeded on ${{ runner.os }}"

      - name: Test install.sh (Windows WSL)
        if: runner.os == 'Windows'
        shell: bash
        run: |
          # Windows runner has WSL2 pre-installed
          wsl bash install.sh --dry-run || { echo "install.sh failed on WSL2"; exit 1; }
          echo "✓ install.sh succeeded on Windows WSL2"

      - name: Lint shell scripts
        if: runner.os == 'Linux'
        shell: bash
        run: |
          # shellcheck pre-installed on ubuntu-latest
          shellcheck install.sh shell-integration.sh || echo "Shellcheck warnings found (non-blocking)"
```

**Source:** [GitHub Actions multi-platform testing](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners)

### Example 3: Enhanced install.sh with Platform Detection

```bash
#!/usr/bin/env bash
# HarnessSync installation script
# Supports: macOS, Linux, Windows (WSL2/Git Bash/native)

set -euo pipefail

# Colors for output (ANSI codes)
BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
RED="\033[31m"
NC="\033[0m"

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false

# Parse arguments
for arg in "$@"; do
  case $arg in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
  esac
done

echo -e "\n${BOLD}${BLUE}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${BLUE}║  HarnessSync Installation            ║${NC}"
echo -e "${BOLD}${BLUE}║  Claude Code → Codex + Gemini + OC    ║${NC}"
echo -e "${BOLD}${BLUE}╚═══════════════════════════════════════╝${NC}\n"

# Detect operating system
OS_TYPE="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
  OS_TYPE="macos"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
  OS_TYPE="linux"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
  OS_TYPE="windows"
elif command -v wslpath >/dev/null 2>&1; then
  OS_TYPE="wsl"
fi

echo -e "${BLUE}[1/5] Detected platform: $OS_TYPE${NC}"

# Create target directories
echo -e "\n${BLUE}[2/5] Creating target directories${NC}"

if [[ "$DRY_RUN" == true ]]; then
  echo "  [DRY RUN] Would create ~/.codex/skills/"
  echo "  [DRY RUN] Would create ~/.gemini/"
  echo "  [DRY RUN] Would create ~/.config/opencode/{skills,agents,commands}/"
else
  mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
  mkdir -p "${CODEX_HOME:-$HOME/.codex}/.agents/skills"
  mkdir -p "$HOME/.gemini"
  mkdir -p "$HOME/.config/opencode/skills"
  mkdir -p "$HOME/.config/opencode/agents"
  mkdir -p "$HOME/.config/opencode/commands"
  echo -e "  ${GREEN}✓${NC} Target directories created"
fi

# Detect shell and configure integration
echo -e "\n${BLUE}[3/5] Shell integration setup${NC}"

SHELL_RC=""
if [[ -n "${ZSH_VERSION:-}" ]] || [[ "$SHELL" == *"zsh"* ]]; then
  SHELL_RC="$HOME/.zshrc"
elif [[ -n "${BASH_VERSION:-}" ]] || [[ "$SHELL" == *"bash"* ]]; then
  SHELL_RC="$HOME/.bashrc"
fi

if [[ -z "$SHELL_RC" ]]; then
  echo -e "  ${YELLOW}⚠${NC} Could not detect shell (bash/zsh)"
  echo -e "    Add manually to your shell profile:"
  echo -e "    source \"$PLUGIN_ROOT/shell-integration.sh\""
else
  if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY RUN] Would add to $SHELL_RC"
  else
    if grep -q "HarnessSync" "$SHELL_RC" 2>/dev/null; then
      echo -e "  ${GREEN}✓${NC} Already in $SHELL_RC"
    else
      echo "" >> "$SHELL_RC"
      echo "# HarnessSync: Claude Code → All Harnesses auto-sync" >> "$SHELL_RC"
      echo "source \"$PLUGIN_ROOT/shell-integration.sh\"" >> "$SHELL_RC"
      echo -e "  ${GREEN}✓${NC} Added to $SHELL_RC"
    fi
  fi
fi

# Platform-specific instructions
echo -e "\n${BLUE}[4/5] Platform-specific setup${NC}"

case $OS_TYPE in
  macos)
    echo -e "  ${GREEN}✓${NC} macOS native symlinks supported"
    ;;
  linux)
    echo -e "  ${GREEN}✓${NC} Linux native symlinks supported"
    ;;
  windows)
    echo -e "  ${YELLOW}⚠${NC} Windows native detected"
    echo -e "    Using junction points for directories (no admin required)"
    echo -e "    File symlinks will be copied (not linked)"
    ;;
  wsl)
    echo -e "  ${GREEN}✓${NC} WSL2 detected (native symlinks supported)"
    ;;
  *)
    echo -e "  ${YELLOW}⚠${NC} Unknown platform"
    echo -e "    Symlinks may not work correctly"
    ;;
esac

# Completion message
echo -e "\n${BOLD}${GREEN}═══════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Installation complete!${NC}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════${NC}"

if [[ "$DRY_RUN" == false ]]; then
  echo ""
  echo -e "  ${BOLD}Next steps:${NC}"
  echo -e "  1. Restart your shell: ${BLUE}source $SHELL_RC${NC}"
  echo -e "  2. Verify installation: ${BLUE}/sync-status${NC}"
  echo ""
fi
```

**Source:** Derived from project's existing install.sh + [shell integration best practices](https://mac.install.guide/terminal/configuration)

---

## Open Questions

### Question 1: Should HarnessSync Submit to Official Anthropic Marketplace?

**What we know:** Anthropic maintains curated marketplace at `github.com/anthropics/claude-plugins-official`. Submission requires review process.

**What's unclear:** Review criteria, timeline, acceptance rate. Whether custom marketplace vs official provides better discoverability.

**Recommendation:** Start with custom marketplace (username/HarnessSync). Submit to official marketplace after v1.0 release and community validation. Provides flexibility during early development.

**Trade-off:** Official marketplace = better discoverability, custom marketplace = faster iteration.

### Question 2: Should install.sh Include Python Version Validation?

**What we know:** HarnessSync requires Python 3.10+ for stdlib features (structural pattern matching, tomllib in 3.11+).

**What's unclear:** Whether install.sh should check Python version and fail early, or let plugin fail at runtime with clear error message.

**Recommendation:** Add Python version check with clear error message: "Python 3.10+ required (found 3.9). Install via: brew install python@3.10". Non-blocking warning, not hard failure.

**Trade-off:** Early validation = better UX, but adds complexity to install script.

### Question 3: Should Plugin Support Pre-Release Versions (0.9.0-beta)?

**What we know:** Semantic versioning supports pre-release tags (0.9.0-beta.1, 1.0.0-rc.1). Marketplace can host multiple versions.

**What's unclear:** Whether Claude Code plugin system supports version pinning, beta channels, or upgrade paths from beta to stable.

**Recommendation:** Use pre-release versions (0.9.0-beta) during Phase 7 testing. Release 1.0.0 only after all Level 3 deferred validations pass. Document upgrade path in README.

**Trade-off:** Beta releases = early feedback, but may confuse users expecting stable release.

---

## Sources

### Primary (HIGH confidence)

**Official Claude Code Documentation:**
- [Create and distribute a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces) — Complete marketplace.json specification, plugin sources, GitHub distribution
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference) — Directory structure, validation commands, schema reference
- [Plugin directory structure](https://code.claude.com/docs/en/plugins-reference#plugin-directory-structure) — Correct component placement at root level
- [GitHub-hosted runners](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners) — Official GitHub Actions platform documentation

**Project Context:**
- STATE.md (Phase 1-6 decisions) — Zero-dependency constraint, existing install.sh, symlink fallback strategy
- PITFALLS.md (Phase 4 packaging pitfalls) — Component directory structure errors, marketplace validation failures
- STACK.md (Python 3.10+, stdlib-only) — Runtime requirements, platform compatibility

### Secondary (MEDIUM confidence)

- [Multi-platform testing with GitHub Actions](https://levelup.gitconnected.com/utilizing-github-actions-to-build-and-test-on-multiple-platforms-a7fe3aa6ce2a) (2024) — Matrix workflow patterns for macOS/Linux/Windows
- [Shell Integration - Mac Install Guide](https://mac.install.guide/terminal/configuration) (2026) — Shell detection, .bashrc vs .zshrc best practices
- [Windows symlinks vs WSL symlinks](https://blog.trailofbits.com/2024/02/12/why-windows-cant-follow-wsl-symlinks/) (2024) — Junction vs symlink compatibility
- [WSL2 symlink best practices](https://www.mslinn.com/wsl/9000-wsl-volumes.html) (2026) — Junction recommendations for cross-platform compatibility
- [NVM shell integration](https://deepwiki.com/nvm-sh/nvm/3.2-shell-integration) (2024) — Idempotent rc file modification patterns

### Tertiary (LOW confidence - context only)

- [Claude Code Plugin Marketplace](https://claudemarketplaces.com/) — Community marketplace aggregator (not official)
- [Building Claude Code Plugins tutorial](https://www.datacamp.com/tutorial/how-to-build-claude-code-plugins) (2026) — General plugin development guide

---

## Metadata

**Confidence breakdown:**
- Plugin validation requirements: HIGH — Official `claude plugin validate` documentation is authoritative
- marketplace.json structure: HIGH — Official Anthropic specification with examples
- Cross-platform installation: MEDIUM-HIGH — GitHub Actions matrix well-documented, but Windows junction testing requires manual verification
- Shell integration: HIGH — Pattern used by nvm, rbenv, and other CLI tools for 10+ years
- Production considerations: MEDIUM — Based on pitfalls research and community experience, not empirical data

**Research date:** 2026-02-15
**Valid until:** 90 days (plugin structure is stable, but Claude Code may introduce breaking changes in marketplace schema)

**Research scope:** Phase 7 focuses on packaging mechanics, not runtime functionality. Runtime validation (sync operations, MCP server, hooks) covered by Phase 1-6 deferred validations. Cross-platform testing focuses on installation, not full integration testing.
