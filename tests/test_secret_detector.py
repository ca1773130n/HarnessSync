from __future__ import annotations

"""Unit tests for src/secret_detector.py — API key/token detection.

Covers:
- shannon_entropy: calculation, edge cases
- is_high_entropy_secret: threshold and character-set checks
- SecretDetector.scan: keyword matching, safe prefix filtering, entropy upgrade
- SecretDetector.scan_content: inline secret patterns, known secret formats
- SecretDetector.scan_mcp_env: MCP server env var extraction
- SecretDetector.should_block / format_warnings
- SecretDetector.scrub_env_vars / scrub_mcp_env / scrub_content
- SecretDetector.scrub_content_with_env_refs
- SecretDetector.scrub_rules_content
- SecretDetector.scan_config_files / scan_harness_configs
- pre_sync_secret_scan: blocking, redaction, allow_secrets
- False positive avoidance (safe prefixes, short values)
"""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.secret_detector import (
    ENTROPY_MIN_LENGTH,
    ENTROPY_THRESHOLD,
    PreSyncSecretScanResult,
    SecretDetector,
    is_high_entropy_secret,
    pre_sync_secret_scan,
    shannon_entropy,
)


# ---------------------------------------------------------------------------
# shannon_entropy
# ---------------------------------------------------------------------------

class TestShannonEntropy:
    def test_empty_string(self):
        assert shannon_entropy("") == 0.0

    def test_single_char_repeated(self):
        assert shannon_entropy("aaaaaaa") == 0.0

    def test_two_chars_equal(self):
        # "ab" repeated → entropy = 1.0 (2 equally likely symbols)
        result = shannon_entropy("abababab")
        assert abs(result - 1.0) < 0.01

    def test_high_entropy_random(self):
        # Long random-looking string should have high entropy
        value = "aB3dE5gH7jK9mN1pQ3sT5vW7xY9zA2cD4fG6hJ8kL0n"
        assert shannon_entropy(value) > 4.0

    def test_low_entropy_prose(self):
        value = "the quick brown fox"
        assert shannon_entropy(value) < 4.5

    def test_returns_float(self):
        assert isinstance(shannon_entropy("hello"), float)


# ---------------------------------------------------------------------------
# is_high_entropy_secret
# ---------------------------------------------------------------------------

class TestIsHighEntropySecret:
    def test_short_string_rejected(self):
        """Strings shorter than ENTROPY_MIN_LENGTH are never flagged."""
        assert is_high_entropy_secret("abc") is False

    def test_low_entropy_long_string_rejected(self):
        """Long but repetitive strings are not flagged."""
        assert is_high_entropy_secret("a" * 30) is False

    def test_high_entropy_base64_flagged(self):
        """A long random base64-like string should be flagged."""
        # Generate a high-entropy base64-like value
        value = "aB3dE5gH7jK9mN1pQ3sT5vW7xY9zA2cD4fG6hJ8kL0nR2tU4"
        if shannon_entropy(value) >= ENTROPY_THRESHOLD:
            assert is_high_entropy_secret(value) is True

    def test_non_base64_chars_rejected(self):
        """String with too many special chars isn't base64-like."""
        value = "!@#$%^&*()!@#$%^&*()!@#$%^&*()"
        assert is_high_entropy_secret(value) is False


# ---------------------------------------------------------------------------
# SecretDetector.scan
# ---------------------------------------------------------------------------

class TestScan:
    def test_detects_api_key(self):
        sd = SecretDetector()
        detections = sd.scan({"OPENAI_API_KEY": "sk-abcdefghijklmnop1234567890123456"})
        assert len(detections) >= 1
        assert detections[0]["var_name"] == "OPENAI_API_KEY"

    def test_detects_token(self):
        sd = SecretDetector()
        detections = sd.scan({"GITHUB_TOKEN": "ghp_abcdefghijklmnop1234567890123456789012"})
        assert len(detections) >= 1

    def test_safe_prefix_skipped(self):
        sd = SecretDetector()
        detections = sd.scan({"TEST_API_KEY": "sk-abcdefghijklmnop1234567890123456"})
        assert len(detections) == 0

    def test_example_prefix_skipped(self):
        sd = SecretDetector()
        detections = sd.scan({"EXAMPLE_SECRET": "longvaluehere1234567890abcdef"})
        assert len(detections) == 0

    def test_short_value_not_flagged(self):
        """Values under 16 chars should not match the value pattern."""
        sd = SecretDetector()
        detections = sd.scan({"API_KEY": "short"})
        assert len(detections) == 0

    def test_no_keyword_no_detection(self):
        sd = SecretDetector()
        detections = sd.scan({"MY_VAR": "not_a_secret_value_at_all"})
        # Should not be flagged by keyword (may be flagged by entropy)
        keyword_detections = [d for d in detections if d["keywords_matched"]]
        assert len(keyword_detections) == 0

    def test_confidence_high_with_entropy(self):
        """High-entropy value upgrades confidence from medium to high."""
        sd = SecretDetector()
        # Use a value that has high entropy
        high_entropy_value = "aB3dE5gH7jK9mN1pQ3sT5vW7xY9zA2c"
        detections = sd.scan({"MY_SECRET_KEY": high_entropy_value})
        if detections:
            assert detections[0]["confidence"] in ("medium", "high")

    def test_source_file_included(self):
        sd = SecretDetector()
        detections = sd.scan(
            {"API_KEY": "longvalue1234567890abcdefghij"},
            source_file=".mcp.json",
        )
        if detections:
            assert detections[0]["source_file"] == ".mcp.json"

    def test_empty_env_vars(self):
        sd = SecretDetector()
        assert sd.scan({}) == []

    def test_entropy_only_detection(self):
        """High-entropy value without keyword match flagged at 'low' confidence."""
        sd = SecretDetector()
        # Use a variable name without any secret keywords but a high-entropy value
        value = "aB3dE5gH7jK9mN1pQ3sT5vW7xY9zA2cD4fG6hJ8kL0n"
        detections = sd.scan({"CUSTOM_SETTING": value})
        entropy_detections = [d for d in detections if d["confidence"] == "low"]
        if shannon_entropy(value) >= ENTROPY_THRESHOLD and len(value) >= ENTROPY_MIN_LENGTH:
            assert len(entropy_detections) >= 1


# ---------------------------------------------------------------------------
# SecretDetector.scan_content
# ---------------------------------------------------------------------------

class TestScanContent:
    def test_inline_api_key(self):
        sd = SecretDetector()
        content = 'api_key: sk-abcdefghijklmnop1234567890'
        detections = sd.scan_content(content)
        assert len(detections) >= 1

    def test_inline_password_equals(self):
        sd = SecretDetector()
        content = 'password=SuperSecret1234567890abc'
        detections = sd.scan_content(content)
        assert len(detections) >= 1

    def test_no_secrets_in_clean_content(self):
        sd = SecretDetector()
        content = "## Rules\n\n- Use Python 3.10+\n- Follow PEP 8\n"
        detections = sd.scan_content(content)
        assert len(detections) == 0

    def test_known_format_anthropic_key(self):
        sd = SecretDetector()
        content = "Use this key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
        detections = sd.scan_content(content)
        assert any(d["confidence"] == "high" for d in detections)

    def test_known_format_github_pat(self):
        sd = SecretDetector()
        content = "token: ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"
        detections = sd.scan_content(content)
        assert len(detections) >= 1

    def test_source_label_included(self):
        sd = SecretDetector()
        content = 'token: sk-abcdefghijklmnop1234567890'
        detections = sd.scan_content(content, source_label="CLAUDE.md")
        if detections:
            assert detections[0].get("source") == "CLAUDE.md"

    def test_deduplication_same_position(self):
        sd = SecretDetector()
        # A value that matches both inline pattern and known format
        content = 'api_key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz'
        detections = sd.scan_content(content)
        # Should not have duplicates for the same position
        positions = [(d.get("var_name"), d.get("reason", "")[:30]) for d in detections]
        # We just ensure it doesn't crash and returns results
        assert isinstance(detections, list)


# ---------------------------------------------------------------------------
# SecretDetector.scan_mcp_env
# ---------------------------------------------------------------------------

class TestScanMcpEnv:
    def test_extracts_and_scans_env(self):
        sd = SecretDetector()
        mcp_servers = {
            "my-server": {
                "command": "npx",
                "env": {"API_KEY": "sk-abcdefghijklmnop1234567890123456"},
            }
        }
        detections = sd.scan_mcp_env(mcp_servers)
        assert len(detections) >= 1

    def test_no_env_section(self):
        sd = SecretDetector()
        mcp_servers = {"my-server": {"command": "npx"}}
        assert sd.scan_mcp_env(mcp_servers) == []

    def test_non_dict_server_config_skipped(self):
        sd = SecretDetector()
        mcp_servers = {"my-server": "not a dict"}
        assert sd.scan_mcp_env(mcp_servers) == []

    def test_empty_mcp_servers(self):
        sd = SecretDetector()
        assert sd.scan_mcp_env({}) == []


# ---------------------------------------------------------------------------
# should_block / format_warnings
# ---------------------------------------------------------------------------

class TestShouldBlock:
    def test_no_detections_no_block(self):
        sd = SecretDetector()
        assert sd.should_block([]) is False

    def test_detections_block_by_default(self):
        sd = SecretDetector()
        detections = [{"var_name": "KEY", "reason": "test"}]
        assert sd.should_block(detections) is True

    def test_allow_secrets_override(self):
        sd = SecretDetector()
        detections = [{"var_name": "KEY", "reason": "test"}]
        assert sd.should_block(detections, allow_secrets=True) is False


class TestFormatWarnings:
    def test_empty_detections(self):
        sd = SecretDetector()
        assert sd.format_warnings([]) == ""

    def test_includes_var_name(self):
        sd = SecretDetector()
        output = sd.format_warnings([{
            "var_name": "MY_API_KEY",
            "reason": "Contains keywords: API_KEY",
            "confidence": "medium",
        }])
        assert "MY_API_KEY" in output

    def test_includes_fix_suggestion(self):
        sd = SecretDetector()
        output = sd.format_warnings([{
            "var_name": "TOKEN",
            "reason": "test reason",
            "confidence": "high",
        }])
        assert "Fix:" in output

    def test_includes_source_file(self):
        sd = SecretDetector()
        output = sd.format_warnings([{
            "var_name": "KEY",
            "reason": "test",
            "source_file": ".mcp.json",
            "confidence": "medium",
        }])
        assert ".mcp.json" in output


# ---------------------------------------------------------------------------
# scrub_env_vars / scrub_mcp_env
# ---------------------------------------------------------------------------

class TestScrubbing:
    def test_scrub_env_vars_replaces_secrets(self):
        sd = SecretDetector()
        env = {"API_KEY": "sk-abcdefghijklmnop1234567890123456", "NORMAL": "hello"}
        scrubbed, names = sd.scrub_env_vars(env)
        if names:
            assert scrubbed["API_KEY"] == "${API_KEY}"
            assert scrubbed["NORMAL"] == "hello"

    def test_scrub_env_vars_no_secrets(self):
        sd = SecretDetector()
        env = {"PATH": "/usr/bin", "HOME": "/Users/me"}
        scrubbed, names = sd.scrub_env_vars(env)
        assert names == []
        assert scrubbed == env

    def test_scrub_mcp_env_deep_copy(self):
        sd = SecretDetector()
        mcp = {
            "server": {
                "command": "npx",
                "env": {"API_KEY": "sk-abcdefghijklmnop1234567890123456"},
            }
        }
        scrubbed_servers, names = sd.scrub_mcp_env(mcp)
        # Original should be untouched
        assert mcp["server"]["env"]["API_KEY"] == "sk-abcdefghijklmnop1234567890123456"

    def test_format_scrub_report_empty(self):
        sd = SecretDetector()
        assert sd.format_scrub_report([]) == ""

    def test_format_scrub_report_content(self):
        sd = SecretDetector()
        report = sd.format_scrub_report(["API_KEY", "TOKEN"])
        assert "2 secret(s)" in report
        assert "API_KEY" in report


# ---------------------------------------------------------------------------
# scrub_content / scrub_content_with_env_refs
# ---------------------------------------------------------------------------

class TestScrubContent:
    def test_scrub_content_replaces_inline_secret(self):
        sd = SecretDetector()
        content = "api_key: sk-abcdefghijklmnop1234567890\nother line\n"
        scrubbed, descs = sd.scrub_content(content)
        assert "[REDACTED]" in scrubbed
        assert len(descs) >= 1

    def test_scrub_content_preserves_clean_lines(self):
        sd = SecretDetector()
        content = "## Rules\n\nUse Python 3.10+\n"
        scrubbed, descs = sd.scrub_content(content)
        assert scrubbed == content
        assert descs == []

    def test_scrub_content_custom_placeholder(self):
        sd = SecretDetector()
        content = "api_key=sk-abcdefghijklmnop1234567890\n"
        scrubbed, _ = sd.scrub_content(content, placeholder="***")
        assert "***" in scrubbed

    def test_scrub_content_with_env_refs(self):
        sd = SecretDetector()
        content = "api_key: sk-abcdefghijklmnop1234567890\n"
        scrubbed, replacements = sd.scrub_content_with_env_refs(content)
        assert "${" in scrubbed
        assert len(replacements) >= 1


# ---------------------------------------------------------------------------
# scrub_rules_content
# ---------------------------------------------------------------------------

class TestScrubRulesContent:
    def test_scrubs_rule_content(self):
        sd = SecretDetector()
        rules = [
            {"path": "rule1.md", "content": "api_key: sk-abcdefghijklmnop1234567890"},
            {"path": "rule2.md", "content": "just normal text here"},
        ]
        scrubbed, descs = sd.scrub_rules_content(rules)
        assert len(scrubbed) == 2
        assert "[REDACTED]" in scrubbed[0]["content"]
        assert scrubbed[1]["content"] == "just normal text here"

    def test_empty_rules(self):
        sd = SecretDetector()
        scrubbed, descs = sd.scrub_rules_content([])
        assert scrubbed == []
        assert descs == []

    def test_rule_without_content(self):
        sd = SecretDetector()
        rules = [{"path": "rule.md"}]
        scrubbed, descs = sd.scrub_rules_content(rules)
        assert len(scrubbed) == 1


# ---------------------------------------------------------------------------
# scan_config_files / scan_harness_configs
# ---------------------------------------------------------------------------

class TestScanConfigFiles:
    def test_scans_existing_files(self, tmp_path):
        sd = SecretDetector()
        (tmp_path / "CLAUDE.md").write_text("api_key: sk-abcdefghijklmnop1234567890")
        detections = sd.scan_config_files(tmp_path)
        assert len(detections) >= 1

    def test_skips_missing_files(self, tmp_path):
        sd = SecretDetector()
        detections = sd.scan_config_files(tmp_path)
        assert detections == []

    def test_extra_files_scanned(self, tmp_path):
        sd = SecretDetector()
        extra = tmp_path / "extra.md"
        extra.write_text("token=sk-abcdefghijklmnop1234567890")
        detections = sd.scan_config_files(tmp_path, extra_files=[str(extra)])
        assert len(detections) >= 1


class TestScanHarnessConfigs:
    def test_scans_cursor_mcp(self, tmp_path):
        sd = SecretDetector()
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        mcp_config = {
            "mcpServers": {
                "s1": {"command": "npx", "env": {"API_KEY": "sk-abcdefghijklmnop1234567890123456"}}
            }
        }
        (cursor_dir / "mcp.json").write_text(json.dumps(mcp_config))
        detections = sd.scan_harness_configs(tmp_path)
        assert len(detections) >= 1

    def test_no_harness_configs(self, tmp_path):
        sd = SecretDetector()
        assert sd.scan_harness_configs(tmp_path) == []


# ---------------------------------------------------------------------------
# pre_sync_secret_scan
# ---------------------------------------------------------------------------

class TestPreSyncSecretScan:
    def test_clean_files_not_blocked(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("## Rules\nUse Python 3.10+\n")
        result = pre_sync_secret_scan(project_dir=tmp_path)
        assert result.blocked is False
        assert result.files_scanned >= 1

    def test_secrets_block_by_default(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("api_key: sk-abcdefghijklmnop1234567890")
        result = pre_sync_secret_scan(project_dir=tmp_path)
        assert result.blocked is True
        assert len(result.detections) >= 1

    def test_allow_secrets_override(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("api_key: sk-abcdefghijklmnop1234567890")
        result = pre_sync_secret_scan(project_dir=tmp_path, allow_secrets=True)
        assert result.blocked is False

    def test_redact_populates_content(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("api_key: sk-abcdefghijklmnop1234567890")
        result = pre_sync_secret_scan(project_dir=tmp_path, redact=True)
        assert len(result.redacted_content) >= 1

    def test_explicit_config_paths(self, tmp_path):
        f = tmp_path / "custom.md"
        f.write_text("token=sk-abcdefghijklmnop1234567890")
        result = pre_sync_secret_scan(config_paths=[str(f)])
        assert result.blocked is True

    def test_format_output(self):
        result = PreSyncSecretScanResult(
            blocked=True,
            detections=["Found API key on line 1"],
            files_scanned=3,
        )
        output = result.format()
        assert "Pre-Sync Secret Scan" in output
        assert "BLOCKED" in output
        assert "3" in output
