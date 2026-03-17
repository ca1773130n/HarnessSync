from __future__ import annotations

"""Tests for iteration 72 product-ideation improvements.

Covers:
- Tamper-Evident Audit Log (item 28): AuditLog / AuditEntry / VerificationReport
- Sync Policy Enforcement (item 25): PolicyEnforcer / PolicyReport / PolicyCheckResult
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audit_log import AuditLog, AuditEntry, VerificationReport, _chain_hash
from src.sync_policy import (
    PolicyEnforcer,
    PolicyReport,
    PolicyCheckResult,
    PolicyViolation,
    _PROJECT_POLICY_NAME,
)


# ---------------------------------------------------------------------------
# AuditLog tests
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_record_creates_file(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        log.record("sync", targets=["codex"], files_changed=["AGENTS.md"])
        assert log.log_path.exists()

    def test_record_returns_entry(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        entry = log.record("sync", targets=["codex", "gemini"])
        assert entry.event == "sync"
        assert "codex" in entry.targets
        assert entry.chain_hash  # non-empty

    def test_multiple_entries_chained(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        e1 = log.record("sync", targets=["codex"])
        e2 = log.record("rollback", targets=["codex"])
        # Each entry has a unique chain hash
        assert e1.chain_hash != e2.chain_hash

    def test_verify_empty_log(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        report = log.verify()
        assert report.ok is True
        assert report.entry_count == 0

    def test_verify_valid_log(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        for i in range(5):
            log.record("sync", targets=[f"target{i}"])
        report = log.verify()
        assert report.ok is True
        assert report.entry_count == 5

    def test_verify_detects_tampering(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        log.record("sync", targets=["codex"])
        log.record("sync", targets=["gemini"])

        # Tamper: overwrite the first line
        lines = log.log_path.read_text().splitlines()
        original = json.loads(lines[0])
        original["targets"] = ["HACKED"]
        lines[0] = json.dumps(original, separators=(",", ":"), sort_keys=True)
        log.log_path.write_text("\n".join(lines) + "\n")

        report = log.verify()
        assert report.ok is False
        assert report.violation_index is not None

    def test_verify_detects_line_deletion(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        log.record("sync", targets=["codex"])
        log.record("sync", targets=["gemini"])
        log.record("sync", targets=["opencode"])

        # Delete the middle line
        lines = log.log_path.read_text().splitlines()
        del lines[1]
        log.log_path.write_text("\n".join(lines) + "\n")

        report = log.verify()
        assert report.ok is False

    def test_tail_returns_recent_entries(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        for i in range(15):
            log.record("sync", targets=[f"t{i}"])
        tail = log.tail(5)
        assert len(tail) == 5
        # Most recent 5
        assert tail[-1].targets == ["t14"]

    def test_tail_empty_log(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        assert log.tail() == []

    def test_format_timeline_empty(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        text = log.format_timeline()
        assert "empty" in text.lower()

    def test_format_timeline_shows_events(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        log.record("sync", targets=["codex", "gemini"], files_changed=["AGENTS.md"])
        text = log.format_timeline()
        assert "sync" in text
        assert "codex" in text

    def test_extra_kwargs_stored(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        entry = log.record("sync", targets=["codex"], scope="project")
        assert entry.extra.get("scope") == "project"

    def test_verification_report_format_ok(self):
        r = VerificationReport(ok=True, entry_count=3)
        text = r.format()
        assert "OK" in text or "verified" in text.lower()

    def test_verification_report_format_violation(self):
        r = VerificationReport(
            ok=False, entry_count=2,
            first_violation="hash mismatch", violation_index=1,
        )
        text = r.format()
        assert "VIOLATION" in text
        assert "1" in text

    def test_chain_hash_genesis(self):
        h = _chain_hash("", '{"event":"sync"}')
        assert len(h) == 64  # SHA256 hex

    def test_chain_hash_changes_with_prev(self):
        h1 = _chain_hash("", '{"event":"sync"}')
        h2 = _chain_hash('{"event":"previous"}', '{"event":"sync"}')
        assert h1 != h2

    def test_audit_entry_from_dict_roundtrip(self, tmp_path):
        log = AuditLog(project_dir=tmp_path)
        original = log.record("drift_detected", targets=["cursor"])
        d = original.to_dict()
        restored = AuditEntry.from_dict(d)
        assert restored.event == original.event
        assert restored.targets == original.targets
        assert restored.chain_hash == original.chain_hash


# ---------------------------------------------------------------------------
# PolicyEnforcer tests
# ---------------------------------------------------------------------------

class TestPolicyEnforcer:
    def _policy(self, **kwargs) -> dict:
        base = {
            "version": 1,
            "must_sync": [],
            "must_not_sync": [],
            "protected_sections": [],
            "require_review_for": [],
            "target_overrides": {},
        }
        base.update(kwargs)
        return base

    def _source(self, **kwargs) -> dict:
        base = {
            "rules": "# My Rule\nDo good things.\n",
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {"myserver": {}},
            "settings": {"theme": "dark"},
        }
        base.update(kwargs)
        return base

    def test_no_policy_passes(self, tmp_path):
        enforcer = PolicyEnforcer(project_dir=tmp_path)
        report = enforcer.check(self._source(), "codex")
        assert not report.blocked
        assert not report.violations

    def test_must_sync_present_passes(self, tmp_path):
        enforcer = PolicyEnforcer(policy=self._policy(must_sync=["rules"]))
        report = enforcer.check(self._source(), "codex")
        assert not report.blocked

    def test_must_sync_absent_blocks(self, tmp_path):
        enforcer = PolicyEnforcer(policy=self._policy(must_sync=["rules"]))
        report = enforcer.check(self._source(rules=""), "codex")
        assert report.blocked
        assert any(v.section == "rules" for v in report.violations)

    def test_must_not_sync_present_blocks(self):
        enforcer = PolicyEnforcer(policy=self._policy(must_not_sync=["mcp"]))
        report = enforcer.check(self._source(), "codex")
        assert report.blocked
        assert any(v.section == "mcp" for v in report.violations)

    def test_must_not_sync_absent_passes(self):
        enforcer = PolicyEnforcer(policy=self._policy(must_not_sync=["mcp"]))
        report = enforcer.check(self._source(mcp={}), "codex")
        assert not report.blocked

    def test_target_override_must_not_sync(self):
        policy = self._policy(target_overrides={"aider": {"must_not_sync": ["mcp"]}})
        enforcer = PolicyEnforcer(policy=policy)
        report_aider = enforcer.check(self._source(), "aider")
        report_codex = enforcer.check(self._source(), "codex")
        assert report_aider.blocked
        assert not report_codex.blocked

    def test_require_review_emits_warnings(self):
        enforcer = PolicyEnforcer(policy=self._policy(require_review_for=["mcp"]))
        report = enforcer.check(self._source(), "codex")
        assert not report.blocked
        assert report.warnings

    def test_protected_section_missing_warns(self):
        enforcer = PolicyEnforcer(
            policy=self._policy(protected_sections=["Security Policy"])
        )
        report = enforcer.check(self._source(), "codex")
        # Should have a warning-level violation for the missing section
        assert any(v.severity == "warning" for v in report.violations)

    def test_protected_section_present_passes(self):
        enforcer = PolicyEnforcer(
            policy=self._policy(protected_sections=["My Rule"])
        )
        report = enforcer.check(self._source(), "codex")
        assert not report.blocked

    def test_check_all_aggregates(self):
        enforcer = PolicyEnforcer(policy=self._policy(must_not_sync=["mcp"]))
        result = enforcer.check_all(self._source(), targets=["codex", "gemini"])
        assert result.total_errors == 2  # mcp present in both

    def test_strip_forbidden_sections(self):
        enforcer = PolicyEnforcer(policy=self._policy(must_not_sync=["mcp"]))
        stripped = enforcer.strip_forbidden_sections(self._source(), "codex")
        assert "mcp" not in stripped
        assert "rules" in stripped

    def test_strip_no_forbidden_returns_same_keys(self):
        enforcer = PolicyEnforcer(policy=self._policy())
        source = self._source()
        stripped = enforcer.strip_forbidden_sections(source, "codex")
        assert set(stripped.keys()) == set(source.keys())

    def test_has_policy_false_without_file(self, tmp_path):
        enforcer = PolicyEnforcer(project_dir=tmp_path)
        assert enforcer.has_policy is False

    def test_has_policy_true_with_inline(self):
        enforcer = PolicyEnforcer(policy=self._policy(must_sync=["rules"]))
        assert enforcer.has_policy is True

    def test_format_policy_summary_no_policy(self, tmp_path):
        enforcer = PolicyEnforcer(project_dir=tmp_path)
        text = enforcer.format_policy_summary()
        assert "No policy" in text

    def test_format_policy_summary_with_policy(self):
        enforcer = PolicyEnforcer(
            policy=self._policy(
                must_sync=["rules"],
                must_not_sync=["mcp"],
                description="Acme policy",
            )
        )
        text = enforcer.format_policy_summary()
        assert "rules" in text
        assert "mcp" in text

    def test_policy_file_loaded_from_project(self, tmp_path):
        policy_data = self._policy(must_sync=["rules"])
        (tmp_path / _PROJECT_POLICY_NAME).write_text(
            json.dumps(policy_data), encoding="utf-8"
        )
        enforcer = PolicyEnforcer(project_dir=tmp_path)
        assert enforcer.has_policy is True

    def test_policy_report_format_blocked(self):
        report = PolicyReport(
            target="codex",
            violations=[
                PolicyViolation(
                    severity="error",
                    section="mcp",
                    target="codex",
                    message="mcp not allowed",
                )
            ],
        )
        text = report.format()
        assert "BLOCK" in text.upper() or "BLOCKED" in text.upper()

    def test_policy_report_format_clean(self):
        report = PolicyReport(target="codex")
        text = report.format()
        assert "passed" in text.lower()

    def test_policy_check_result_any_blocked(self):
        r1 = PolicyReport(target="codex")
        r2 = PolicyReport(
            target="gemini",
            violations=[PolicyViolation("error", "mcp", "gemini", "forbidden")],
        )
        result = PolicyCheckResult(reports=[r1, r2])
        assert result.any_blocked is True

    def test_policy_check_result_none_blocked(self):
        r1 = PolicyReport(target="codex")
        r2 = PolicyReport(target="gemini")
        result = PolicyCheckResult(reports=[r1, r2])
        assert result.any_blocked is False

    def test_get_must_not_sync_sections(self):
        policy = self._policy(
            must_not_sync=["mcp"],
            target_overrides={"cursor": {"must_not_sync": ["skills"]}},
        )
        enforcer = PolicyEnforcer(policy=policy)
        codex_forbidden = enforcer.get_must_not_sync_sections("codex")
        cursor_forbidden = enforcer.get_must_not_sync_sections("cursor")
        assert "mcp" in codex_forbidden
        assert "skills" in cursor_forbidden
        assert "mcp" in cursor_forbidden  # inherited from global
