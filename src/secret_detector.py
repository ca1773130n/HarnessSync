from __future__ import annotations

"""
Secret detection for environment variables and config file content.

Scans environment variables and inline config content using keyword+regex approach
combined with Shannon entropy analysis to reduce false positives.
Based on TruffleHog/Secrets-Patterns-DB patterns.

Entropy analysis (item 4):
High-entropy strings (>= 4.5 bits/char for base64-like values) that appear
in secret-looking positions are flagged even without keyword matches.
This catches API keys, JWTs, and bearer tokens that use non-obvious variable names.
"""

import math
import re

from src.utils.logger import Logger


# Shannon entropy threshold for high-entropy secret detection (bits per character)
# Base64 has theoretical max ~6 bits/char; real secrets typically >= 4.5
ENTROPY_THRESHOLD = 4.5

# Minimum length for entropy-based detection (short strings have naturally high entropy)
ENTROPY_MIN_LENGTH = 20

# Characters expected in base64/hex/JWT tokens
_BASE64_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
_HEX_CHARS = set("0123456789abcdefABCDEF")


def shannon_entropy(value: str) -> float:
    """Calculate Shannon entropy (bits per character) for a string.

    Higher values indicate more randomness. Real English text is typically
    ~4.0 bits/char; random secrets are typically >= 4.5 bits/char.

    Args:
        value: String to analyze.

    Returns:
        Entropy in bits per character. Returns 0.0 for empty strings.
    """
    if not value:
        return 0.0
    length = len(value)
    freq: dict[str, int] = {}
    for ch in value:
        freq[ch] = freq.get(ch, 0) + 1
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def is_high_entropy_secret(value: str) -> bool:
    """Return True if value looks like a high-entropy secret token.

    Uses Shannon entropy combined with character-set analysis to detect
    base64-encoded secrets, API keys, and bearer tokens that don't appear
    in environment variable names with obvious keywords.

    Args:
        value: Candidate secret value.

    Returns:
        True if value is long enough AND has entropy >= ENTROPY_THRESHOLD
        AND consists mostly of base64 or hex characters.
    """
    if len(value) < ENTROPY_MIN_LENGTH:
        return False
    entropy = shannon_entropy(value)
    if entropy < ENTROPY_THRESHOLD:
        return False
    # Require the value to be predominantly base64/hex characters
    base64_ratio = sum(1 for ch in value if ch in _BASE64_CHARS) / len(value)
    return base64_ratio >= 0.85


# Keyword patterns to match in env var names
SECRET_KEYWORDS = [
    'API_KEY', 'APIKEY', 'API-KEY',
    'SECRET', 'SECRET_KEY',
    'PASSWORD', 'PASSWD', 'PWD',
    'TOKEN', 'ACCESS_TOKEN', 'AUTH_TOKEN',
    'PRIVATE_KEY',
    # AI provider keys
    'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY',
    'GOOGLE_API_KEY', 'COHERE_API_KEY', 'MISTRAL_API_KEY',
    'AZURE_OPENAI_API_KEY', 'AWS_SECRET_ACCESS_KEY',
    # VCS & CI
    'GITHUB_TOKEN', 'GITLAB_TOKEN', 'GH_TOKEN', 'CI_TOKEN',
    'NPM_TOKEN', 'PYPI_TOKEN',
    # Database / infra
    'DATABASE_URL', 'DB_PASSWORD', 'REDIS_URL',
    'MONGO_URI', 'POSTGRES_PASSWORD',
    # Generic credential names
    'CREDENTIAL', 'CREDENTIALS', 'CERT', 'CERTIFICATE',
    'CLIENT_SECRET', 'APP_SECRET',
]

# Patterns that look like inline secrets in file content (e.g. CLAUDE.md)
# Matches: key=VALUE, key: VALUE, key="VALUE" where VALUE looks like a secret
_INLINE_SECRET_RE = re.compile(
    r'(?:api[_-]?key|secret[_-]?key?|password|passwd|token|access[_-]token|private[_-]key'
    r'|anthropic[_-]api[_-]key|openai[_-]api[_-]key|github[_-]token|client[_-]secret'
    r'|app[_-]secret|database[_-]url|db[_-]password|credentials?)'
    r'\s*[:=]\s*["\']?([A-Za-z0-9_\-+=/.@:]{16,})["\']?',
    re.IGNORECASE,
)

# Well-known secret value formats — matched directly against values regardless of key name.
# These patterns catch hardcoded secrets even when the variable name isn't suspicious.
KNOWN_SECRET_FORMATS: list[re.Pattern] = [
    # Anthropic API key: sk-ant-api03-...
    re.compile(r'\bsk-ant-[a-zA-Z0-9_\-]{20,}\b'),
    # OpenAI API key: sk-...
    re.compile(r'\bsk-[a-zA-Z0-9]{32,}\b'),
    # GitHub PAT (classic): ghp_... or github_pat_...
    re.compile(r'\bghp_[a-zA-Z0-9]{36,}\b'),
    re.compile(r'\bgithub_pat_[a-zA-Z0-9_]{59}\b'),
    # AWS access key ID
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    # Generic JWT: three base64url segments separated by dots
    re.compile(r'\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b'),
    # Slack Bot/App tokens
    re.compile(r'\bxox[bpoa]-[0-9A-Za-z\-]{10,}\b'),
    # Stripe secret key
    re.compile(r'\bsk_(?:live|test)_[a-zA-Z0-9]{24,}\b'),
    # Google API key
    re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b'),
]

# Safe prefixes to whitelist (testing/example values)
SAFE_PREFIXES = [
    'TEST_', 'EXAMPLE_', 'DEMO_',
    'MOCK_', 'FAKE_', 'DUMMY_'
]

# Value pattern: 16+ chars of alphanumeric/special chars
# Reduces false positives by filtering out short/simple values
SECRET_VALUE_PATTERN = re.compile(r'^[A-Za-z0-9_\-+=/.]{16,}$')


class SecretDetector:
    """
    Environment variable secret scanner.

    Uses keyword+regex approach with whitelist filtering to detect
    potential secrets in environment variables. Blocks sync by default
    with allow_secrets override.

    CRITICAL: Never logs or displays actual secret values.
    """

    def __init__(self):
        """Initialize SecretDetector with Logger instance."""
        self.logger = Logger()

    def scan(self, env_vars: dict[str, str]) -> list[dict]:
        """
        Scan environment variables for potential secrets.

        Args:
            env_vars: Dict mapping var_name -> var_value

        Returns:
            List of detection dicts with keys:
                - var_name: Environment variable name
                - keywords_matched: List of matched keywords
                - confidence: 'medium' (regex+keyword approach)
                - reason: Human-readable detection reason

            Empty list if no secrets detected.
        """
        detections = []

        for var_name, var_value in env_vars.items():
            # Skip if var has safe prefix (TEST_, EXAMPLE_, etc.)
            var_upper = var_name.upper()
            if any(var_upper.startswith(prefix) for prefix in SAFE_PREFIXES):
                continue

            # Check if var name contains any secret keyword
            matched_keywords = [
                keyword for keyword in SECRET_KEYWORDS
                if keyword in var_upper
            ]

            if not matched_keywords:
                # No secret keywords in name — fall through to entropy check
                if is_high_entropy_secret(var_value):
                    detections.append({
                        "var_name": var_name,
                        "keywords_matched": [],
                        "confidence": "low",
                        "reason": (
                            f"High-entropy value detected (Shannon entropy "
                            f"{shannon_entropy(var_value):.2f} bits/char >= {ENTROPY_THRESHOLD})"
                        ),
                    })
                continue

            # Check if value matches complexity pattern (16+ chars)
            if not SECRET_VALUE_PATTERN.match(var_value):
                # Value too short or not complex enough
                continue

            # Upgrade confidence to 'high' when entropy also confirms the finding
            entropy = shannon_entropy(var_value)
            confidence = "high" if entropy >= ENTROPY_THRESHOLD else "medium"

            # All checks passed - potential secret detected
            detections.append({
                "var_name": var_name,
                "keywords_matched": matched_keywords,
                "confidence": confidence,
                "reason": (
                    f"Contains keywords: {', '.join(matched_keywords)}"
                    + (f"; high entropy ({entropy:.2f} bits/char)" if confidence == "high" else "")
                ),
            })

        return detections

    def scan_env_with_entropy(self, env_vars: dict[str, str]) -> list[dict]:
        """Scan environment variables using entropy analysis only (no keyword matching).

        Finds high-entropy values that look like secrets regardless of variable name.
        Useful as a secondary pass to catch obfuscated credential names.

        CRITICAL: Never logs or displays actual secret values.

        Args:
            env_vars: Dict mapping var_name -> var_value.

        Returns:
            List of detection dicts for high-entropy values not already caught
            by the keyword-based ``scan()`` method.
        """
        keyword_detections = {d["var_name"] for d in self.scan(env_vars)}
        detections = []
        for var_name, var_value in env_vars.items():
            if var_name in keyword_detections:
                continue  # already caught by keyword scan
            var_upper = var_name.upper()
            if any(var_upper.startswith(prefix) for prefix in SAFE_PREFIXES):
                continue
            if is_high_entropy_secret(var_value):
                detections.append({
                    "var_name": var_name,
                    "keywords_matched": [],
                    "confidence": "low",
                    "reason": (
                        f"High-entropy value (Shannon entropy "
                        f"{shannon_entropy(var_value):.2f} bits/char)"
                    ),
                })
        return detections

    def scan_content(self, content: str, source_label: str = "content") -> list[dict]:
        """Scan text content (e.g. CLAUDE.md) for inline secrets.

        Looks for patterns like ``api_key: sk-abc123...`` or
        ``password=supersecretvalue123`` that should not be synced.

        CRITICAL: Never logs or displays actual secret values.

        Args:
            content: Raw text content to scan.
            source_label: Human-readable label for the source (e.g. filename).

        Returns:
            List of detection dicts with keys:
                - var_name: Matched keyword (e.g. "api_key")
                - keywords_matched: List of matched keywords
                - confidence: 'low' (heuristic inline scan)
                - reason: Human-readable detection reason
                - source: source_label
        """
        detections = []
        seen_positions: set[tuple[int, int]] = set()

        for line_num, line in enumerate(content.splitlines(), start=1):
            # Check key=value inline patterns
            for m in _INLINE_SECRET_RE.finditer(line):
                pos = (line_num, m.start())
                if pos in seen_positions:
                    continue
                seen_positions.add(pos)
                keyword = m.group(0).split("=")[0].split(":")[0].strip()
                detections.append({
                    "var_name": keyword,
                    "keywords_matched": [keyword],
                    "confidence": "medium",
                    "reason": f"Inline secret pattern on line {line_num} in {source_label}",
                    "source": source_label,
                })

            # Check for well-known secret formats (API keys, tokens, JWTs)
            for pattern in KNOWN_SECRET_FORMATS:
                for m in pattern.finditer(line):
                    pos = (line_num, m.start())
                    if pos in seen_positions:
                        continue
                    seen_positions.add(pos)
                    detections.append({
                        "var_name": f"<literal on line {line_num}>",
                        "keywords_matched": [],
                        "confidence": "high",
                        "reason": (
                            f"Matches known secret format pattern on line {line_num}"
                            f" in {source_label} — matches pattern: {pattern.pattern[:60]}"
                        ),
                        "source": source_label,
                    })

        return detections

    def scan_config_files(
        self,
        project_dir,
        extra_files: list | None = None,
    ) -> list[dict]:
        """Scan all relevant config files in a project for inline secrets.

        Called automatically before every sync operation. Checks CLAUDE.md,
        CLAUDE.local.md, and any extra files provided. Returns detections from
        all scanned files merged into a single list.

        CRITICAL: Never logs or displays actual secret values.

        Args:
            project_dir: Path to project root directory.
            extra_files: Additional file paths (absolute) to scan.

        Returns:
            Merged list of detection dicts from all scanned files.
        """
        from pathlib import Path

        project_dir = Path(project_dir)
        default_files = [
            project_dir / "CLAUDE.md",
            project_dir / "CLAUDE.local.md",
            project_dir / ".claude" / "settings.json",
            project_dir / ".mcp.json",
        ]
        paths = list(default_files)
        if extra_files:
            paths.extend(Path(p) for p in extra_files)

        all_detections: list[dict] = []
        for path in paths:
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hits = self.scan_content(content, source_label=path.name)
            all_detections.extend(hits)

        return all_detections

    def scan_mcp_env(self, mcp_servers: dict) -> list[dict]:
        """
        Extract and scan environment variables from MCP server configs.

        Args:
            mcp_servers: Dict of MCP server configurations, each with optional 'env' dict

        Returns:
            List of detection dicts (same format as scan())
        """
        # Extract env vars from all MCP servers
        all_env_vars = {}

        for server_name, server_config in mcp_servers.items():
            if not isinstance(server_config, dict):
                continue

            env = server_config.get("env", {})
            if isinstance(env, dict):
                all_env_vars.update(env)

        # Scan extracted env vars
        return self.scan(all_env_vars)

    def scrub_env_vars(self, env_vars: dict[str, str]) -> tuple[dict[str, str], list[str]]:
        """Replace detected secret values with ${VAR_NAME} placeholder references.

        Instead of blocking sync, this method produces a version of env_vars
        safe to write to target configs — secret values are replaced with
        portable env var reference syntax (``${VAR_NAME}``).

        CRITICAL: Never logs or displays actual secret values.

        Args:
            env_vars: Dict mapping var_name -> var_value.

        Returns:
            Tuple of (scrubbed_env_vars, scrubbed_names) where:
              - scrubbed_env_vars: New dict with secret values replaced by
                ``${VAR_NAME}`` placeholders.
              - scrubbed_names: List of var names that were scrubbed.
        """
        detections = self.scan(env_vars)
        detected_names = {d["var_name"] for d in detections}

        scrubbed: dict[str, str] = {}
        scrubbed_names: list[str] = []

        for var_name, var_value in env_vars.items():
            if var_name in detected_names:
                scrubbed[var_name] = f"${{{var_name}}}"
                scrubbed_names.append(var_name)
            else:
                scrubbed[var_name] = var_value

        return scrubbed, scrubbed_names

    def scrub_mcp_env(self, mcp_servers: dict) -> tuple[dict, list[str]]:
        """Replace secret env var values in MCP server configs with placeholder refs.

        Produces a scrubbed copy of mcp_servers suitable for writing to
        target harness config files. Secret values are replaced with
        ``${VAR_NAME}`` placeholders — recipients set the real value from
        their local environment.

        This enables ``--scrub-secrets`` mode: sync proceeds with redacted
        env vars instead of blocking. The resulting config is portable and
        does not contain credentials.

        CRITICAL: Never logs or displays actual secret values.

        Args:
            mcp_servers: Dict of MCP server configs (same format as
                         SourceReader.get_mcp_servers() output).

        Returns:
            Tuple of (scrubbed_servers, scrubbed_var_names) where:
              - scrubbed_servers: Deep copy of mcp_servers with secret env
                values replaced by ``${VAR_NAME}`` references.
              - scrubbed_var_names: Flat list of variable names that were
                scrubbed across all servers.
        """
        import copy

        scrubbed_servers = copy.deepcopy(mcp_servers)
        all_scrubbed: list[str] = []

        for server_name, server_config in scrubbed_servers.items():
            if not isinstance(server_config, dict):
                continue

            env = server_config.get("env", {})
            if not isinstance(env, dict) or not env:
                continue

            scrubbed_env, scrubbed_names = self.scrub_env_vars(env)
            if scrubbed_names:
                server_config["env"] = scrubbed_env
                all_scrubbed.extend(scrubbed_names)

        return scrubbed_servers, all_scrubbed

    def format_scrub_report(self, scrubbed_names: list[str]) -> str:
        """Format a human-readable report of scrubbed variables.

        CRITICAL: Never includes actual secret values.

        Args:
            scrubbed_names: List of var names replaced with placeholders.

        Returns:
            Formatted report string, or empty string if nothing was scrubbed.
        """
        if not scrubbed_names:
            return ""

        lines = [
            f"\n⚙ Scrubbed {len(scrubbed_names)} secret(s) from MCP env vars "
            "(replaced with ${VAR_NAME} placeholders):"
        ]
        for name in scrubbed_names:
            lines.append(f"  · {name} → ${{{name}}}")
        lines.append(
            "\nRecipients must set these env vars locally before using the config."
        )
        return "\n".join(lines)

    def should_block(self, detections: list[dict], allow_secrets: bool = False) -> bool:
        """
        Determine if sync should be blocked based on detections.

        Args:
            detections: List of detection dicts from scan()
            allow_secrets: Override flag to allow sync despite detections

        Returns:
            True if sync should be blocked (detections present and not overridden)
            False if sync should proceed
        """
        if not detections:
            return False

        if allow_secrets:
            return False

        return True

    def format_warnings(self, detections: list[dict]) -> str:
        """
        Format secret detection warnings for user output.

        CRITICAL: Never includes actual secret values in output.

        Args:
            detections: List of detection dicts from scan()

        Returns:
            Formatted warning string with variable names (values masked)
        """
        if not detections:
            return ""

        lines = []
        lines.append(f"\n⚠ Detected {len(detections)} potential secret(s) in environment variables:")

        for detection in detections:
            var_name = detection["var_name"]
            reason = detection["reason"]
            lines.append(f"  · {var_name} — {reason}")

        lines.append("\nSecrets should not be synced to target configs.")
        lines.append("Use --allow-secrets to override this warning (NOT recommended).")

        return "\n".join(lines)

    def scrub_content(self, content: str, placeholder: str = "[REDACTED]") -> tuple[str, list[str]]:
        """Replace inline secret values in plain text content with a placeholder.

        Scans each line for patterns like ``api_key: sk-abc123`` or
        ``password=supersecretvalue123`` and replaces the *value* portion
        with ``placeholder``. The key name is preserved so the context is
        not lost, but the secret value is never written to target configs.

        This extends scrub_mcp_env() to cover inline secrets inside CLAUDE.md
        rules text and other plaintext config files.

        CRITICAL: Never logs or displays actual secret values.

        Args:
            content: Raw text to scrub (e.g. CLAUDE.md content).
            placeholder: Replacement string for detected secret values.
                         Default: "[REDACTED]"

        Returns:
            Tuple of (scrubbed_content, scrubbed_descriptions) where:
              - scrubbed_content: Content with secret values replaced.
              - scrubbed_descriptions: List of human-readable descriptions
                of what was scrubbed (e.g. "api_key on line 12"), without
                revealing the actual secret values.
        """
        scrubbed_lines: list[str] = []
        descriptions: list[str] = []

        for line_num, line in enumerate(content.splitlines(keepends=True), start=1):
            new_line = line
            for m in _INLINE_SECRET_RE.finditer(line):
                # m.group(0) is e.g. "api_key: sk-abc123"
                # We preserve the key= part and replace only the value
                matched = m.group(0)
                # Find the separator (: or =) and replace everything after it
                sep_pos = -1
                for sep in (":", "="):
                    idx = matched.find(sep)
                    if idx != -1 and (sep_pos == -1 or idx < sep_pos):
                        sep_pos = idx
                if sep_pos != -1:
                    key_part = matched[: sep_pos + 1]
                    new_line = new_line.replace(matched, f"{key_part} {placeholder}", 1)
                    keyword = matched[:sep_pos].strip()
                    descriptions.append(f"{keyword} on line {line_num}")

            # Entropy-based scrubbing for standalone high-entropy tokens
            # Only applies to tokens that look like they're assigned values
            # (prevents scrubbing normal prose words)
            for word in new_line.split():
                clean = word.strip("\"',;()")
                if len(clean) >= ENTROPY_MIN_LENGTH and is_high_entropy_secret(clean):
                    # Extra guard: must contain mixed-case or digits to avoid
                    # false positives on long lowercase prose words
                    has_upper = any(c.isupper() for c in clean)
                    has_digit = any(c.isdigit() for c in clean)
                    if has_upper and has_digit:
                        new_line = new_line.replace(clean, placeholder, 1)
                        descriptions.append(f"high-entropy token on line {line_num}")
                        break  # One replacement per line for entropy scrubbing

            scrubbed_lines.append(new_line)

        return "".join(scrubbed_lines), descriptions

    def scrub_rules_content(self, rules: list[dict]) -> tuple[list[dict], list[str]]:
        """Scrub inline secrets from a list of rule dicts returned by SourceReader.

        Each rule dict has a ``content`` key containing the rule text.
        This method returns a new list with secrets scrubbed from content.

        Args:
            rules: List of rule dicts (path, content keys).

        Returns:
            Tuple of (scrubbed_rules, all_descriptions) where:
              - scrubbed_rules: New list of rule dicts with secrets removed.
              - all_descriptions: Flat list of scrub descriptions.
        """
        import copy

        scrubbed_rules: list[dict] = []
        all_descriptions: list[str] = []

        for rule in rules:
            rule_copy = copy.copy(rule)
            content = rule.get("content", "")
            if content:
                scrubbed_content, descs = self.scrub_content(content)
                rule_copy["content"] = scrubbed_content
                if descs:
                    src = rule.get("path", "rule")
                    all_descriptions.extend(f"{src}: {d}" for d in descs)
            scrubbed_rules.append(rule_copy)

        return scrubbed_rules, all_descriptions
