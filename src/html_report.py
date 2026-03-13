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


# ---------------------------------------------------------------------------
# Capability Gap Report (item 2)
# ---------------------------------------------------------------------------

def generate_capability_gap_report(
    gap_data: dict[str, list[dict]],
    title: str = "HarnessSync Capability Gap Report",
    include_workarounds: bool = True,
) -> str:
    """Generate a self-contained HTML capability gap report.

    Produces a shareable single-file HTML report showing which Claude Code
    features have no equivalent in each target harness, along with optional
    workaround suggestions. Helps teams understand what they're giving up
    before committing to a target harness.

    Args:
        gap_data: Dict mapping target_name -> list of gap dicts.
            Each gap dict has keys:
              - "feature": str — Claude Code feature name (e.g. "Skills")
              - "status": str — "unsupported" | "partial" | "workaround"
              - "description": str — What's missing
              - "workaround": str — Optional workaround suggestion
        title: HTML page title.
        include_workarounds: If False, omit the workaround column.

    Returns:
        Self-contained HTML string (no external dependencies).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    _STATUS_COLORS = {
        "unsupported": ("#ff6b6b", "#3a1010"),
        "partial": ("#ffd93d", "#3a3010"),
        "workaround": ("#6bcb77", "#103a15"),
    }

    def _status_badge(status: str) -> str:
        bg, fg = _STATUS_COLORS.get(status.lower(), ("#888", "#222"))
        label = _escape(status.upper())
        return (
            f'<span style="background:{bg};color:{fg};padding:2px 8px;'
            f'border-radius:4px;font-size:0.8em;font-weight:bold">{label}</span>'
        )

    # Build per-target sections
    target_sections = []
    all_targets = sorted(gap_data.keys())
    for target in all_targets:
        gaps = gap_data[target]
        if not gaps:
            target_sections.append(
                f'<section><h2>{_escape(target.capitalize())}</h2>'
                f'<p style="color:#6bcb77">✓ No capability gaps detected.</p></section>'
            )
            continue

        unsupported = sum(1 for g in gaps if g.get("status") == "unsupported")
        partial = sum(1 for g in gaps if g.get("status") == "partial")
        workaround = sum(1 for g in gaps if g.get("status") == "workaround")

        summary = (
            f'<p><strong>{len(gaps)} gap(s):</strong> '
            f'{unsupported} unsupported, {partial} partial, {workaround} with workaround</p>'
        )

        wk_col = '<th>Workaround</th>' if include_workarounds else ''
        rows = []
        for gap in gaps:
            feature = _escape(gap.get("feature", ""))
            status = gap.get("status", "unsupported")
            desc = _escape(gap.get("description", ""))
            wk = _escape(gap.get("workaround", "—"))
            wk_cell = f'<td>{wk}</td>' if include_workarounds else ''
            rows.append(
                f'<tr><td>{feature}</td><td>{_status_badge(status)}</td>'
                f'<td>{desc}</td>{wk_cell}</tr>'
            )

        rows_html = "\n".join(rows)
        target_sections.append(f'''<section>
<h2>{_escape(target.capitalize())}</h2>
{summary}
<table>
  <thead><tr><th>Feature</th><th>Status</th><th>Description</th>{wk_col}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</section>''')

    sections_html = "\n".join(target_sections)
    total_gaps = sum(len(v) for v in gap_data.values())

    nav_links = " | ".join(
        f'<a href="#{t}" style="color:#58a6ff">{_escape(t.capitalize())}</a>'
        for t in all_targets
    )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape(title)}</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
  background: #0d1117; color: #c9d1d9;
  margin: 0; padding: 20px; line-height: 1.6;
}}
h1 {{ color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
h2 {{ color: #79c0ff; margin-top: 30px; border-left: 4px solid #30363d; padding-left: 12px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
th {{ background: #161b22; color: #58a6ff; padding: 8px 12px; text-align: left; border: 1px solid #30363d; }}
td {{ padding: 8px 12px; border: 1px solid #21262d; vertical-align: top; }}
tr:nth-child(even) td {{ background: #161b22; }}
section {{ margin-bottom: 40px; }}
.meta {{ color: #8b949e; font-size: 0.9em; margin-bottom: 20px; }}
.nav {{ margin-bottom: 24px; }}
</style>
</head>
<body>
<h1>{_escape(title)}</h1>
<div class="meta">Generated: {now} &nbsp;|&nbsp; {total_gaps} total gap(s) across {len(all_targets)} target(s)</div>
<div class="nav">{nav_links}</div>
{sections_html}
</body>
</html>'''


def write_capability_gap_report(
    gap_data: dict[str, list[dict]],
    output_path: Path,
    title: str = "HarnessSync Capability Gap Report",
    include_workarounds: bool = True,
) -> None:
    """Write the capability gap HTML report to a file.

    Args:
        gap_data: Dict mapping target_name -> list of gap dicts (see
                  ``generate_capability_gap_report`` for schema).
        output_path: Path to write the HTML file.
        title: Page title.
        include_workarounds: If False, omit the workaround column.
    """
    content = generate_capability_gap_report(gap_data, title, include_workarounds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Item 21 — Web-Based Skill & Rule Browser
# ---------------------------------------------------------------------------


def generate_skill_browser(
    skills: list[dict],
    targets: list[str] | None = None,
    title: str = "HarnessSync Skill & Rule Browser",
) -> str:
    """Generate a standalone HTML skill and rule browser.

    Creates a self-contained HTML page with a searchable table showing all
    synced skills and their translation status (exact / approximate / lossy)
    per target harness. Users can filter by confidence level and see which
    skills need manual review before syncing.

    Args:
        skills: List of skill dicts, each with keys:
                - name (str): Skill name
                - content (str): Raw SKILL.md content
                - path (str): Source file path (optional)
                - translated (dict): {target: translated_content} (optional)
                - scores (dict): {target: score_dict} (optional; auto-computed if absent)
        targets: Target harness names to include in columns.
                 Defaults to ["codex", "gemini", "cursor", "aider", "windsurf"].
        title: HTML page title.

    Returns:
        Self-contained HTML string.
    """
    from src.skill_translator import (
        translate_skill_content,
        score_translation,
        compute_confidence_level,
        ConfidenceLevel,
    )

    if targets is None:
        targets = ["codex", "gemini", "cursor", "aider", "windsurf"]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Confidence badge colours
    _BADGE = {
        ConfidenceLevel.EXACT:       ("badge-exact",       "#3fb950", "exact"),
        ConfidenceLevel.APPROXIMATE: ("badge-approx",      "#d29922", "approx"),
        ConfidenceLevel.LOSSY:       ("badge-lossy",       "#f85149", "lossy"),
    }

    # Build rows
    rows_html: list[str] = []
    for skill in skills:
        name = _escape(skill.get("name", "?"))
        path = _escape(skill.get("path", ""))
        content = skill.get("content", "")
        preview = _escape(content[:120].replace("\n", " "))

        cells = [f'<td class="skill-name">{name}<br><span class="skill-path">{path}</span></td>',
                 f'<td class="skill-preview">{preview}{"…" if len(content) > 120 else ""}</td>']

        for target in targets:
            pre_translated = (skill.get("translated") or {}).get(target)
            if pre_translated is None:
                translated = translate_skill_content(content, target)
            else:
                translated = pre_translated

            pre_score = (skill.get("scores") or {}).get(target)
            if pre_score is None:
                score_result = score_translation(content, translated, target)
            else:
                score_result = pre_score

            level = compute_confidence_level(content, translated, target)
            css_class, colour, label = _BADGE[level]
            score_val = score_result.get("score", 0)
            note = "; ".join(score_result.get("notes", [])[:1])

            cell = (
                f'<td class="confidence-cell">'
                f'<span class="badge {css_class}" title="{_escape(note)}">'
                f'{label} {score_val}%'
                f'</span>'
                f'</td>'
            )
            cells.append(cell)

        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    # Table headers
    header_cells = ["<th>Skill</th>", "<th>Preview</th>"]
    for t in targets:
        header_cells.append(f"<th>{_escape(t)}</th>")
    header_row = "<tr>" + "".join(header_cells) + "</tr>"

    rows_str = "\n".join(rows_html)

    css = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
       background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
h1 { color: #58a6ff; border-bottom: 1px solid #30363d; padding-bottom: 10px; }
.meta { color: #8b949e; font-size: 0.9em; margin-bottom: 16px; }
table { width: 100%; border-collapse: collapse; background: #161b22;
        border: 1px solid #30363d; border-radius: 8px; overflow: hidden; }
th { background: #1c2128; color: #79c0ff; padding: 10px 12px;
     text-align: left; border-bottom: 1px solid #30363d; font-size: 0.85em; }
td { padding: 8px 12px; border-bottom: 1px solid #21262d;
     vertical-align: top; font-size: 0.85em; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1c2128; }
.skill-name { font-weight: bold; color: #58a6ff; white-space: nowrap; }
.skill-path { color: #6e7681; font-size: 0.78em; font-weight: normal; }
.skill-preview { color: #8b949e; max-width: 300px; }
.confidence-cell { text-align: center; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
         font-size: 0.78em; font-weight: bold; cursor: default;
         border: 1px solid transparent; }
.badge-exact  { background: #0d4a1f; color: #3fb950; border-color: #3fb950; }
.badge-approx { background: #3d2a00; color: #d29922; border-color: #d29922; }
.badge-lossy  { background: #490202; color: #f85149; border-color: #f85149; }
.filter-bar { margin-bottom: 12px; display: flex; gap: 10px; align-items: center; }
.filter-bar input { background: #161b22; border: 1px solid #30363d;
                    color: #c9d1d9; padding: 6px 10px; border-radius: 6px;
                    font-size: 0.9em; flex: 1; }
.legend { font-size: 0.8em; color: #8b949e; margin-bottom: 12px; }
.legend span { margin-right: 16px; }
"""

    js = """
function filterSkills() {
    const q = document.getElementById('search').value.toLowerCase();
    const rows = document.querySelectorAll('tbody tr');
    rows.forEach(row => {
        const name = row.querySelector('.skill-name') ?
            row.querySelector('.skill-name').textContent.toLowerCase() : '';
        row.style.display = (!q || name.includes(q)) ? '' : 'none';
    });
}
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<style>{css}</style>
</head>
<body>
<h1>{_escape(title)}</h1>
<div class="meta">Generated: {now} &nbsp;|&nbsp; {len(skills)} skill(s) &nbsp;|&nbsp; {len(targets)} target(s)</div>
<div class="legend">
  <span><span class="badge badge-exact">exact</span> — 100% faithful translation</span>
  <span><span class="badge badge-approx">approx</span> — minor rewriting applied</span>
  <span><span class="badge badge-lossy">lossy</span> — significant capability loss; review manually</span>
</div>
<div class="filter-bar">
  <input id="search" type="text" placeholder="Filter by skill name…" oninput="filterSkills()">
</div>
<table>
<thead>{header_row}</thead>
<tbody>{rows_str}</tbody>
</table>
<script>{js}</script>
</body>
</html>"""


def write_skill_browser(
    skills: list[dict],
    output_path: Path,
    targets: list[str] | None = None,
    title: str = "HarnessSync Skill & Rule Browser",
) -> None:
    """Write the skill browser HTML to a file.

    Args:
        skills: List of skill dicts (see ``generate_skill_browser``).
        output_path: Destination file path.
        targets: Target harness names. Defaults to 5 major targets.
        title: Page title.
    """
    content = generate_skill_browser(skills, targets, title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
