from __future__ import annotations

"""Sync metrics exporter for Prometheus and StatsD (item 28).

Exposes HarnessSync sync events, drift counts, and per-harness health scores
as Prometheus text-format metrics or StatsD UDP datagrams.

Power users and teams running observability stacks can scrape these metrics
to alert on sync failures or config drift, integrating HarnessSync into their
existing monitoring infrastructure.

Usage — Prometheus text format (write to a file for node_exporter textfile):

    from src.sync_metrics import SyncMetricsExporter
    exporter = SyncMetricsExporter(backend="prometheus")
    exporter.record_sync("codex", success=True, files_written=3)
    exporter.record_drift("gemini", drift_count=2)
    print(exporter.render())   # Prometheus text format

Usage — StatsD UDP:

    exporter = SyncMetricsExporter(backend="statsd", statsd_host="localhost")
    exporter.record_sync("codex", success=True, files_written=3)
    exporter.flush_statsd()   # sends UDP datagrams

Prometheus metric names:
    harnesssync_sync_total{target, status}          Counter  — sync operations
    harnesssync_sync_files_written{target}          Gauge    — files written per sync
    harnesssync_drift_events_total{target}          Counter  — drift detections
    harnesssync_health_score{target}                Gauge    — 0-100 health score
    harnesssync_last_sync_timestamp_seconds{target} Gauge    — Unix timestamp
"""

import json
import socket
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# Metrics persistence file — stores counters across process restarts
_METRICS_FILE = Path.home() / ".claude" / "harnesssync_metrics.json"

# StatsD prefix
_STATSD_PREFIX = "harnesssync"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MetricSample:
    """A single metric sample with labels."""
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    help_text: str = ""
    metric_type: str = "gauge"   # "gauge" | "counter" | "summary"

    def label_str(self) -> str:
        if not self.labels:
            return ""
        pairs = ",".join(f'{k}="{v}"' for k, v in sorted(self.labels.items()))
        return "{" + pairs + "}"

    def prometheus_line(self) -> str:
        return f"{self.name}{self.label_str()} {self.value}"

    def statsd_line(self, prefix: str = _STATSD_PREFIX) -> str:
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(self.labels.items()))
        name = f"{prefix}.{self.name}"
        if tag_str:
            name += f",{tag_str}"
        suffix = "|c" if self.metric_type == "counter" else "|g"
        return f"{name}:{self.value}{suffix}"


# ---------------------------------------------------------------------------
# Core exporter
# ---------------------------------------------------------------------------

class SyncMetricsExporter:
    """Record and export HarnessSync metrics in Prometheus or StatsD format.

    Metrics are accumulated in memory and can be rendered to Prometheus
    text format (for scraping or writing to a textfile) or emitted via
    UDP to a StatsD daemon.

    Args:
        backend: "prometheus" or "statsd".
        statsd_host: StatsD server host (default: localhost).
        statsd_port: StatsD server port (default: 8125).
        persist: If True, load/save counters from disk across restarts.
    """

    def __init__(
        self,
        backend: Literal["prometheus", "statsd"] = "prometheus",
        statsd_host: str = "localhost",
        statsd_port: int = 8125,
        persist: bool = True,
    ):
        self.backend = backend
        self.statsd_host = statsd_host
        self.statsd_port = statsd_port
        self.persist = persist

        # counters[name][label_key] -> float
        self._counters: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        # gauges[name][label_key] -> float
        self._gauges: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        # Pending StatsD datagrams
        self._pending_statsd: list[str] = []

        if persist:
            self._load()

    # ------------------------------------------------------------------
    # Recording API
    # ------------------------------------------------------------------

    def record_sync(
        self,
        target: str,
        success: bool,
        files_written: int = 0,
        duration_ms: float | None = None,
    ) -> None:
        """Record a completed sync operation.

        Args:
            target: Target harness name (e.g. "codex", "gemini").
            success: True if sync completed without errors.
            files_written: Number of config files written.
            duration_ms: Sync duration in milliseconds (optional).
        """
        status = "success" if success else "error"
        label_key = f"target={target},status={status}"

        self._counters["harnesssync_sync_total"][label_key] += 1
        self._gauges["harnesssync_sync_files_written"][f"target={target}"] = files_written
        self._gauges["harnesssync_last_sync_timestamp_seconds"][f"target={target}"] = time.time()

        if duration_ms is not None:
            self._gauges["harnesssync_sync_duration_ms"][f"target={target}"] = duration_ms

        # StatsD
        if self.backend == "statsd":
            self._pending_statsd.append(
                f"{_STATSD_PREFIX}.sync.{target}.{status}:1|c"
            )
            self._pending_statsd.append(
                f"{_STATSD_PREFIX}.files_written.{target}:{files_written}|g"
            )

        if self.persist:
            self._save()

    def record_drift(self, target: str, drift_count: int = 1) -> None:
        """Record a drift detection event.

        Args:
            target: Target harness name.
            drift_count: Number of files found to have drifted.
        """
        label_key = f"target={target}"
        self._counters["harnesssync_drift_events_total"][label_key] += drift_count

        if self.backend == "statsd":
            self._pending_statsd.append(
                f"{_STATSD_PREFIX}.drift.{target}:{drift_count}|c"
            )

        if self.persist:
            self._save()

    def record_health_score(self, target: str, score: int) -> None:
        """Record a health score for a target harness (0-100).

        Args:
            target: Target harness name.
            score: Health score 0-100.
        """
        label_key = f"target={target}"
        self._gauges["harnesssync_health_score"][label_key] = float(score)

        if self.backend == "statsd":
            self._pending_statsd.append(
                f"{_STATSD_PREFIX}.health_score.{target}:{score}|g"
            )

        if self.persist:
            self._save()

    def record_conflict(self, target: str) -> None:
        """Record a manual-edit conflict detected for a target.

        Args:
            target: Target harness name.
        """
        label_key = f"target={target}"
        self._counters["harnesssync_conflicts_total"][label_key] += 1

        if self.backend == "statsd":
            self._pending_statsd.append(
                f"{_STATSD_PREFIX}.conflicts.{target}:1|c"
            )

        if self.persist:
            self._save()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Render all metrics in Prometheus text format.

        Returns:
            Multi-line string in Prometheus text exposition format.
        """
        lines: list[str] = []
        ts_ms = int(time.time() * 1000)

        _HELP: dict[str, tuple[str, str]] = {
            "harnesssync_sync_total": (
                "counter", "Total number of sync operations by target and status"
            ),
            "harnesssync_sync_files_written": (
                "gauge", "Number of config files written in the last sync per target"
            ),
            "harnesssync_sync_duration_ms": (
                "gauge", "Duration of the last sync operation in milliseconds"
            ),
            "harnesssync_drift_events_total": (
                "counter", "Total drift detection events per target"
            ),
            "harnesssync_health_score": (
                "gauge", "Config sync health score 0-100 per target harness"
            ),
            "harnesssync_last_sync_timestamp_seconds": (
                "gauge", "Unix timestamp of the last successful sync per target"
            ),
            "harnesssync_conflicts_total": (
                "counter", "Total manual-edit conflicts detected per target"
            ),
        }

        def _parse_labels(label_key: str) -> dict[str, str]:
            result: dict[str, str] = {}
            for part in label_key.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    result[k.strip()] = v.strip()
            return result

        all_metrics: dict[str, tuple[str, dict[str, float]]] = {}
        for name, samples in self._counters.items():
            all_metrics[name] = ("counter", dict(samples))
        for name, samples in self._gauges.items():
            all_metrics[name] = ("gauge", dict(samples))

        for metric_name in sorted(all_metrics):
            mtype, samples = all_metrics[metric_name]
            help_text, _ = _HELP.get(metric_name, ("", ""))[1], _HELP.get(metric_name, ("gauge", ""))[0]
            if metric_name in _HELP:
                help_text = _HELP[metric_name][1]
                mtype = _HELP[metric_name][0]

            lines.append(f"# HELP {metric_name} {help_text}")
            lines.append(f"# TYPE {metric_name} {mtype}")

            for label_key, value in sorted(samples.items()):
                labels = _parse_labels(label_key)
                label_str = ""
                if labels:
                    pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
                    label_str = "{" + pairs + "}"
                lines.append(f"{metric_name}{label_str} {value} {ts_ms}")

            lines.append("")

        return "\n".join(lines)

    def flush_statsd(self) -> int:
        """Send pending StatsD datagrams via UDP.

        Returns:
            Number of datagrams sent.
        """
        if not self._pending_statsd:
            return 0

        sent = 0
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for datagram in self._pending_statsd:
                try:
                    sock.sendto(
                        datagram.encode("utf-8"),
                        (self.statsd_host, self.statsd_port),
                    )
                    sent += 1
                except OSError:
                    pass
            sock.close()
        except OSError:
            pass

        self._pending_statsd.clear()
        return sent

    def write_prometheus_textfile(self, path: Path) -> None:
        """Write Prometheus metrics to a textfile for node_exporter collection.

        Args:
            path: Destination file path (e.g. /var/lib/node_exporter/harnesssync.prom).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".prom.tmp")
        tmp.write_text(self.render(), encoding="utf-8")
        tmp.replace(path)  # Atomic rename

    def get_summary(self) -> dict:
        """Return a summary dict of current metric values.

        Returns:
            Dict with per-target counts and latest values.
        """
        sync_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "error": 0})
        for label_key, count in self._counters.get("harnesssync_sync_total", {}).items():
            parts = {k: v for part in label_key.split(",") for k, v in [part.split("=", 1)] if "=" in part}
            target = parts.get("target", "unknown")
            status = parts.get("status", "unknown")
            sync_totals[target][status] += int(count)

        health_scores = {
            label_key.replace("target=", ""): int(v)
            for label_key, v in self._gauges.get("harnesssync_health_score", {}).items()
        }

        drift_totals = {
            label_key.replace("target=", ""): int(v)
            for label_key, v in self._counters.get("harnesssync_drift_events_total", {}).items()
        }

        return {
            "sync_totals": dict(sync_totals),
            "health_scores": health_scores,
            "drift_totals": drift_totals,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load persisted counter/gauge values from disk."""
        try:
            if _METRICS_FILE.exists():
                data = json.loads(_METRICS_FILE.read_text(encoding="utf-8"))
                for name, samples in data.get("counters", {}).items():
                    self._counters[name].update(samples)
                for name, samples in data.get("gauges", {}).items():
                    self._gauges[name].update(samples)
        except (json.JSONDecodeError, OSError):
            pass  # Start fresh on corruption

    def _save(self) -> None:
        """Persist counter/gauge values to disk."""
        try:
            _METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "counters": {k: dict(v) for k, v in self._counters.items()},
                "gauges": {k: dict(v) for k, v in self._gauges.items()},
            }
            _METRICS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def reset(self) -> None:
        """Clear all accumulated metrics (for testing)."""
        self._counters.clear()
        self._gauges.clear()
        self._pending_statsd.clear()
        if self.persist and _METRICS_FILE.exists():
            try:
                _METRICS_FILE.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Convenience: record metrics from orchestrator results
# ---------------------------------------------------------------------------

def record_sync_results(
    results: dict,
    exporter: SyncMetricsExporter | None = None,
) -> SyncMetricsExporter:
    """Record orchestrator sync results into a metrics exporter.

    Args:
        results: Results dict from SyncOrchestrator.sync_all().
        exporter: Existing exporter to use. Creates a new one if None.

    Returns:
        The exporter with updated metrics.
    """
    if exporter is None:
        exporter = SyncMetricsExporter(persist=True)

    for key, val in results.items():
        if key.startswith("_") or not isinstance(val, dict):
            continue
        target = key
        has_error = any(
            getattr(v, "failed", 0) for v in val.values() if hasattr(v, "failed")
        )
        files_written = sum(
            getattr(v, "synced", 0) for v in val.values() if hasattr(v, "synced")
        )
        exporter.record_sync(target, success=not has_error, files_written=files_written)

    return exporter
