from __future__ import annotations

"""Sync dry-run HTML report generator for HarnessSync.

Generates a self-contained HTML report of a dry-run sync showing:
- Per-target diffs with syntax highlighting
- Parity scores and summary statistics
- MCP server health indicators
- Warnings and compatibility notes

The report is a single HTML file with embedded CSS/JS — shareable with
teammates or saved for documentation without needing a server.
"""

import html
from datetime import datetime, timezone
from pathlib import Path


def _escape(text: str) -> str:
    """HTML-escape text for safe embedding."""
    return html.escape(str(text))


def _diff_to_html(diff_text: str) -> str:
    """Convert unified diff text to HTML with color coding.

    Lines starting with '+' are green, '-' are red, '@' are blue.
    """
    lines_html = []
    for line in diff_text.splitlines():
        escaped = _escape(line)
        if line.startswith("+++") or line.startswith("---"):
            css_class = "diff-file"
        elif line.startswith("+"):
            css_class = "diff-add"
        elif line.startswith("-"):
            css_class = "diff-del"
        elif line.startswith("@@"):
            css_class = "diff-hunk"
        else:
            css_class = "diff-ctx"
        lines_html.append(f'<span class="{css_class}">{escaped}</span>')

    return "<br>".join(lines_html) if lines_html else '<span class="diff-ctx">(no changes)</span>'


_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: #0d1117;
    color: #c9d1d9;
    margin: 0;
    padding: 20px;
    line-height: 1.5;
}
h1 { color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 10px; }
h2 { color: #79c0ff; margin-top: 30px; }
h3 { color: #d2a8ff; }
.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
    margin: 20px 0;
}
.summary-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px;
}
.summary-card .target-name { font-weight: bold; color: #58a6ff; font-size: 1.1em; }
.summary-card .status { font-size: 0.85em; margin-top: 4px; }
.status-ok { color: #3fb950; }
.status-warn { color: #d29922; }
.status-error { color: #f85149; }
.target-section {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    margin: 16px 0;
    overflow: hidden;
}
.target-header {
    background: #1f2937;
    padding: 12px 16px;
    cursor: pointer;
    user-select: none;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.target-header:hover { background: #263340; }
.target-body { padding: 16px; display: none; }
.target-body.expanded { display: block; }
.diff-block {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 12px;
    font-family: 'SFMono-Regular', Consolas, monospace;
    font-size: 0.85em;
    overflow-x: auto;
    margin: 8px 0;
}
.diff-add { color: #3fb950; }
.diff-del { color: #f85149; }
.diff-hunk { color: #79c0ff; }
.diff-file { color: #d2a8ff; }
.diff-ctx { color: #8b949e; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: bold;
}
.badge-ok { background: #1a4429; color: #3fb950; }
.badge-warn { background: #3d2e00; color: #d29922; }
.badge-error { background: #3d1a1a; color: #f85149; }
.badge-info { background: #1a2a4a; color: #58a6ff; }
.warning-box {
    background: #3d2e00;
    border: 1px solid #d29922;
    border-radius: 6px;
    padding: 12px;
    margin: 12px 0;
    color: #d29922;
}
.info-box {
    background: #1a2a4a;
    border: 1px solid #58a6ff;
    border-radius: 6px;
    padding: 12px;
    margin: 12px 0;
    color: #79c0ff;
}
footer {
    margin-top: 40px;
    padding-top: 16px;
    border-top: 1px solid #30363d;
    font-size: 0.8em;
    color: #8b949e;
}
"""

_JS = """
function toggleTarget(id) {
    var body = document.getElementById(id);
    if (body.classList.contains('expanded')) {
        body.classList.remove('expanded');
    } else {
        body.classList.add('expanded');
    }
}
function expandAll() {
    document.querySelectorAll('.target-body').forEach(function(el) {
        el.classList.add('expanded');
    });
}
function collapseAll() {
    document.querySelectorAll('.target-body').forEach(function(el) {
        el.classList.remove('expanded');
    });
}
"""


def generate_html_report(
    dry_run_results: dict,
    project_dir: Path,
    scope: str = "all",
    account: str = None,
    warnings: list[str] = None,
) -> str:
    """Generate a self-contained HTML dry-run report.

    Args:
        dry_run_results: Results dict from SyncOrchestrator.sync_all() with dry_run=True.
        project_dir: Project root directory (for display).
        scope: Sync scope ("user" | "project" | "all").
        account: Account name (if multi-account).
        warnings: Additional warning strings to display.

    Returns:
        HTML string — self-contained, ready to write to a .html file.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    title_suffix = f" — {account}" if account else ""
    title = f"HarnessSync Dry-Run Report{title_suffix}"
    warnings = warnings or []

    # Extract target previews
    targets: list[tuple[str, str]] = []
    for target_name in sorted(dry_run_results.keys()):
        if target_name.startswith("_"):
            continue
        target_results = dry_run_results[target_name]
        if isinstance(target_results, dict) and "preview" in target_results:
            targets.append((target_name, target_results["preview"]))

    # Build summary cards
    summary_cards = []
    for target_name, preview_text in targets:
        has_changes = (
            "@@" in preview_text or
            "[new]" in preview_text.lower() or
            any(line.startswith("+") or line.startswith("-") for line in preview_text.splitlines())
        )
        if has_changes:
            status_cls = "status-warn"
            status_text = "Changes pending"
            badge_cls = "badge-warn"
        else:
            status_cls = "status-ok"
            status_text = "Up to date"
            badge_cls = "badge-ok"

        summary_cards.append(f"""
        <div class="summary-card">
            <div class="target-name">{_escape(target_name)}</div>
            <div class="status {status_cls}">{status_text}</div>
            <span class="badge {badge_cls}">{'changed' if has_changes else 'no change'}</span>
        </div>
        """)

    # Build target sections
    target_sections = []
    for i, (target_name, preview_text) in enumerate(targets):
        section_id = f"target-{i}"
        diff_html = _diff_to_html(preview_text)
        target_sections.append(f"""
        <div class="target-section">
            <div class="target-header" onclick="toggleTarget('{section_id}')">
                <span><strong>{_escape(target_name)}</strong></span>
                <span class="badge badge-info">click to expand</span>
            </div>
            <div class="target-body" id="{section_id}">
                <div class="diff-block">{diff_html}</div>
            </div>
        </div>
        """)

    # Warnings section
    warnings_html = ""
    if warnings:
        warn_items = "\n".join(f"<li>{_escape(w)}</li>" for w in warnings)
        warnings_html = f"""
        <div class="warning-box">
            <strong>Warnings:</strong>
            <ul>{warn_items}</ul>
        </div>
        """

    if not targets:
        no_targets_html = '<div class="info-box">No target previews available.</div>'
    else:
        no_targets_html = ""

    cards_html = "\n".join(summary_cards)
    sections_html = "\n".join(target_sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{_escape(title)}</h1>
<p>
    Generated: <strong>{_escape(now)}</strong> &nbsp;|&nbsp;
    Project: <strong>{_escape(str(project_dir))}</strong> &nbsp;|&nbsp;
    Scope: <strong>{_escape(scope)}</strong>
    <span class="badge badge-info">dry-run</span>
</p>

{warnings_html}

<h2>Summary ({len(targets)} target{'s' if len(targets) != 1 else ''})</h2>
<div class="summary-grid">
{cards_html}
</div>

<p>
    <button onclick="expandAll()" style="margin-right:8px;padding:6px 12px;cursor:pointer;">Expand all</button>
    <button onclick="collapseAll()" style="padding:6px 12px;cursor:pointer;">Collapse all</button>
</p>

<h2>Per-Target Diffs</h2>
{no_targets_html}
{sections_html}

<footer>
    Generated by HarnessSync dry-run &mdash; No files were modified.
</footer>
<script>{_JS}</script>
</body>
</html>
"""


def write_html_report(
    dry_run_results: dict,
    output_path: Path,
    project_dir: Path,
    scope: str = "all",
    account: str = None,
    warnings: list[str] = None,
) -> None:
    """Generate and write an HTML dry-run report to a file.

    Args:
        dry_run_results: Dry-run results from SyncOrchestrator.
        output_path: Path to write the HTML file.
        project_dir: Project root directory.
        scope: Sync scope.
        account: Account name.
        warnings: Additional warnings to display.
    """
    html_content = generate_html_report(
        dry_run_results=dry_run_results,
        project_dir=project_dir,
        scope=scope,
        account=account,
        warnings=warnings,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")


def render_skill_heatmap_html(
    skill_names: list[str],
    targets: list[str],
    fidelity_matrix: dict[str, dict[str, str]],
    title: str = "Skill Coverage Heatmap",
) -> str:
    """Generate a self-contained HTML heatmap showing skill sync fidelity.

    Each cell shows how well a skill translates to a specific target harness.
    Cell colors:
      - Green (#4caf50):  "full" — syncs with full fidelity
      - Yellow (#ffc107): "partial" — translates with some fidelity loss
      - Red (#f44336):    "none" — no equivalent in target
      - Grey (#9e9e9e):   "unknown" — not evaluated

    Args:
        skill_names: List of CC skill names (rows).
        targets: List of target harness names (columns).
        fidelity_matrix: Dict mapping skill_name -> {target -> fidelity_str}.
                         fidelity_str is one of "full", "partial", "none".
        title: Page and table title.

    Returns:
        Self-contained HTML string with embedded CSS and no external deps.
    """
    _COLORS = {
        "full":    ("#4caf50", "#fff", "Full"),
        "partial": ("#ffc107", "#333", "Partial"),
        "none":    ("#f44336", "#fff", "None"),
        "unknown": ("#9e9e9e", "#fff", "?"),
    }

    # Build header row
    header_cells = "<th>Skill</th>" + "".join(
        f"<th>{_escape(t)}</th>" for t in targets
    )

    # Build data rows
    body_rows: list[str] = []
    for skill in skill_names:
        skill_fidelity = fidelity_matrix.get(skill, {})
        cells = [f"<td class='skill-name'>{_escape(skill)}</td>"]
        for target in targets:
            fidelity = skill_fidelity.get(target, "unknown")
            bg, fg, label = _COLORS.get(fidelity, _COLORS["unknown"])
            cells.append(
                f"<td style='background:{bg};color:{fg};' title='{label}: {skill} → {target}'>"
                f"{label}</td>"
            )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    # Legend
    legend_items = "".join(
        f"<span style='background:{bg};color:{fg};padding:2px 8px;border-radius:3px;margin:0 4px;'>"
        f"{label}</span>"
        for label, (bg, fg, _) in [
            ("Full", _COLORS["full"]),
            ("Partial", _COLORS["partial"]),
            ("None", _COLORS["none"]),
            ("Unknown", _COLORS["unknown"]),
        ]
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_skills = len(skill_names)
    full_count = sum(
        1 for s in skill_names for t in targets
        if fidelity_matrix.get(s, {}).get(t) == "full"
    )
    total_cells = max(total_skills * len(targets), 1)
    overall_pct = round(100 * full_count / total_cells)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{_escape(title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          margin: 24px; background: #f5f5f5; color: #212121; }}
  h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
  .meta {{ font-size: 0.85em; color: #757575; margin-bottom: 16px; }}
  .summary {{ background: #fff; border-radius: 6px; padding: 12px 16px;
              margin-bottom: 16px; display: inline-block; box-shadow: 0 1px 3px rgba(0,0,0,.15); }}
  table {{ border-collapse: collapse; background: #fff;
           box-shadow: 0 1px 3px rgba(0,0,0,.15); border-radius: 6px; overflow: hidden; }}
  th {{ background: #263238; color: #fff; padding: 8px 14px;
        font-size: 0.8em; text-transform: uppercase; letter-spacing: .05em; }}
  td {{ padding: 7px 14px; font-size: 0.85em; border-bottom: 1px solid #e0e0e0; }}
  td.skill-name {{ font-family: monospace; background: #fafafa; font-weight: 500; }}
  tr:last-child td {{ border-bottom: none; }}
  .legend {{ margin-top: 14px; font-size: 0.8em; }}
</style>
</head>
<body>
<h1>{_escape(title)}</h1>
<div class="meta">Generated {now} by HarnessSync</div>
<div class="summary">
  <strong>{total_skills}</strong> skills &nbsp;|&nbsp;
  <strong>{len(targets)}</strong> targets &nbsp;|&nbsp;
  <strong>{overall_pct}%</strong> full-fidelity cells
</div>
<table>
<thead><tr>{header_cells}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
<div class="legend">Legend: {legend_items}</div>
</body>
</html>
"""
    return html


def write_skill_heatmap(
    skill_names: list[str],
    targets: list[str],
    fidelity_matrix: dict[str, dict[str, str]],
    output_path: Path,
    title: str = "Skill Coverage Heatmap",
) -> None:
    """Write a skill coverage heatmap HTML file.

    Args:
        skill_names: List of CC skill names.
        targets: List of target harness names.
        fidelity_matrix: Dict mapping skill_name -> {target -> fidelity_str}.
        output_path: Path to write the HTML file.
        title: Page title.
    """
    html = render_skill_heatmap_html(skill_names, targets, fidelity_matrix, title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def render_skill_usage_heatmap_html(
    skill_names: list[str],
    targets: list[str],
    usage_matrix: dict[str, dict[str, int]],
    title: str = "Skill Usage Frequency Heatmap",
) -> str:
    """Generate a self-contained HTML heatmap of skill invocation frequency.

    Unlike the fidelity heatmap (which shows translation quality), this heatmap
    shows HOW OFTEN each skill was actually invoked per harness. Cell color
    intensity scales with invocation count:
      - Dark green:  high usage (>= 20 invocations)
      - Medium green: moderate usage (5–19)
      - Light green:  low usage (1–4)
      - Grey:         zero usage

    Args:
        skill_names: List of CC skill names (rows).
        targets: List of target harness names (columns).
        usage_matrix: Dict mapping skill_name -> {target -> invocation_count}.
        title: Page and table title.

    Returns:
        Self-contained HTML string with embedded CSS and no external deps.
    """

    def _cell_style(count: int) -> tuple[str, str]:
        """Return (background, foreground) CSS color for a usage count."""
        if count == 0:
            return "#9e9e9e", "#fff"
        if count < 5:
            return "#c8e6c9", "#333"
        if count < 20:
            return "#4caf50", "#fff"
        return "#1b5e20", "#fff"

    # Build header row
    header_cells = "<th>Skill</th>" + "".join(
        f"<th>{_escape(t)}</th>" for t in targets
    )

    # Column totals for the summary row
    col_totals: dict[str, int] = {t: 0 for t in targets}
    for skill in skill_names:
        for t in targets:
            col_totals[t] += usage_matrix.get(skill, {}).get(t, 0)

    # Build data rows
    body_rows: list[str] = []
    for skill in skill_names:
        skill_usage = usage_matrix.get(skill, {})
        row_total = sum(skill_usage.get(t, 0) for t in targets)
        cells = [f"<td class='skill-name'>{_escape(skill)}</td>"]
        for target in targets:
            count = skill_usage.get(target, 0)
            bg, fg = _cell_style(count)
            label = str(count) if count > 0 else "—"
            cells.append(
                f"<td style='background:{bg};color:{fg};text-align:center;' "
                f"title='{_escape(skill)} invoked {count}× in {target}'>"
                f"{label}</td>"
            )
        # Row total
        cells.append(
            f"<td style='background:#e3f2fd;color:#0d47a1;text-align:center;"
            f"font-weight:bold;'>{row_total}</td>"
        )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    # Footer totals row
    total_cells = [
        "<td style='font-weight:bold;background:#fafafa;'>Total</td>"
    ]
    for t in targets:
        total_cells.append(
            f"<td style='background:#bbdefb;color:#0d47a1;text-align:center;"
            f"font-weight:bold;'>{col_totals[t]}</td>"
        )
    grand_total = sum(col_totals.values())
    total_cells.append(
        f"<td style='background:#1565c0;color:#fff;text-align:center;"
        f"font-weight:bold;'>{grand_total}</td>"
    )
    body_rows.append(f"<tr>{''.join(total_cells)}</tr>")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_skills = len(skill_names)
    active_skills = sum(
        1 for s in skill_names
        if any(usage_matrix.get(s, {}).get(t, 0) > 0 for t in targets)
    )

    legend_items = (
        "<span style='background:#9e9e9e;color:#fff;padding:2px 8px;border-radius:3px;margin:0 4px;'>0 (unused)</span>"
        "<span style='background:#c8e6c9;color:#333;padding:2px 8px;border-radius:3px;margin:0 4px;'>1–4</span>"
        "<span style='background:#4caf50;color:#fff;padding:2px 8px;border-radius:3px;margin:0 4px;'>5–19</span>"
        "<span style='background:#1b5e20;color:#fff;padding:2px 8px;border-radius:3px;margin:0 4px;'>20+ (hot)</span>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{_escape(title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          margin: 24px; background: #f5f5f5; color: #212121; }}
  h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
  .meta {{ font-size: 0.85em; color: #757575; margin-bottom: 16px; }}
  .summary {{ background: #fff; border-radius: 6px; padding: 12px 16px;
              margin-bottom: 16px; display: inline-block; box-shadow: 0 1px 3px rgba(0,0,0,.15); }}
  table {{ border-collapse: collapse; background: #fff;
           box-shadow: 0 1px 3px rgba(0,0,0,.15); border-radius: 6px; overflow: hidden; }}
  th {{ background: #263238; color: #fff; padding: 8px 14px;
        font-size: 0.8em; text-transform: uppercase; letter-spacing: .05em; }}
  td {{ padding: 7px 14px; font-size: 0.85em; border-bottom: 1px solid #e0e0e0; }}
  td.skill-name {{ font-family: monospace; background: #fafafa; font-weight: 500; }}
  tr:last-child td {{ border-bottom: none; }}
  .legend {{ margin-top: 14px; font-size: 0.8em; }}
</style>
</head>
<body>
<h1>{_escape(title)}</h1>
<div class="meta">Generated {now} by HarnessSync</div>
<div class="summary">
  <strong>{total_skills}</strong> skills &nbsp;|&nbsp;
  <strong>{len(targets)}</strong> targets &nbsp;|&nbsp;
  <strong>{active_skills}</strong> skills with at least 1 invocation &nbsp;|&nbsp;
  <strong>{grand_total}</strong> total invocations
</div>
<table>
<thead><tr>{header_cells}<th>Total</th></tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
<div class="legend">Usage legend: {legend_items}</div>
</body>
</html>
"""
    return html


def write_skill_usage_heatmap(
    skill_names: list[str],
    targets: list[str],
    usage_matrix: dict[str, dict[str, int]],
    output_path: Path,
    title: str = "Skill Usage Frequency Heatmap",
) -> None:
    """Write a skill usage frequency heatmap HTML file.

    Args:
        skill_names: List of CC skill names.
        targets: List of target harness names.
        usage_matrix: Dict mapping skill_name -> {target -> invocation_count}.
        output_path: Path to write the HTML file.
        title: Page title.
    """
    html = render_skill_usage_heatmap_html(skill_names, targets, usage_matrix, title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
