"""Self-contained HTML report generator for experiment results."""
from __future__ import annotations

import csv
import html
from datetime import UTC, datetime
from pathlib import Path

_STYLE = """
body{font-family:system-ui,sans-serif;margin:2rem;background:#0f172a;color:#e2e8f0}
h1{color:#38bdf8;margin-bottom:.25rem}
.sub{color:#94a3b8;font-size:.875rem;margin-bottom:2rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th{background:#1e3a5f;color:#7dd3fc;text-align:left;padding:.5rem .75rem;position:sticky;top:0}
td{padding:.4rem .75rem;border-bottom:1px solid #1e293b;white-space:nowrap}
tr:hover td{background:#1e293b}
.keep{color:#4ade80}.discard{color:#f87171}.baseline{color:#facc15}
.chart{background:#1e293b;border-radius:8px;padding:1rem;margin:1.5rem 0}
.chart h2{color:#38bdf8;margin:0 0 .75rem}
svg text{fill:#94a3b8;font-size:11px;font-family:monospace}
"""


def _svg_line_chart(scores: list[float], width: int = 820, height: int = 200) -> str:
    if len(scores) < 2:
        return "<p style='color:#64748b'>Not enough data points for chart.</p>"
    pl, pr, pt, pb = 56, 16, 16, 28
    iw, ih = width - pl - pr, height - pt - pb
    lo, hi = min(scores), max(scores)
    span = hi - lo if hi != lo else 1e-9

    def sx(i: int) -> float:
        return pl + i / (len(scores) - 1) * iw

    def sy(v: float) -> float:
        return pt + ih - (v - lo) / span * ih

    pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(scores))

    ticks = ""
    for k in range(5):
        v = lo + span * k / 4
        y = sy(v)
        ticks += (
            f'<line x1="{pl}" y1="{y:.1f}" x2="{pl+iw}" y2="{y:.1f}" '
            f'stroke="#334155" stroke-dasharray="3,3"/>'
            f'<text x="{pl-4}" y="{y:.1f}" text-anchor="end" '
            f'dominant-baseline="middle">{v:.4f}</text>'
        )
    step = max(1, len(scores) // 10)
    x_labels = "".join(
        f'<text x="{sx(i):.1f}" y="{height-5}" text-anchor="middle">{i+1}</text>'
        for i in range(0, len(scores), step)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{width}px">'
        f"{ticks}{x_labels}"
        f'<polyline points="{pts}" fill="none" stroke="#38bdf8" stroke-width="2"/>'
        f'<circle cx="{sx(len(scores)-1):.1f}" cy="{sy(scores[-1]):.1f}" r="4" '
        f'fill="#38bdf8"/>'
        f"</svg>"
    )


def _row_html(r: dict) -> str:
    st = r.get("status", "")
    css = {"keep": "keep", "discard": "discard", "baseline": "baseline"}.get(st, "")
    score = float(r.get("eval_score", 0))
    return (
        f"<tr>"
        f"<td><code>{html.escape(r.get('commit',''))}</code></td>"
        f"<td class='{css}'>{score:.6f}</td>"
        f"<td>{float(r.get('task_success',0)):.4f}</td>"
        f"<td>{html.escape(str(r.get('latency_ms_p95','')))}</td>"
        f"<td class='{css}'>{html.escape(st)}</td>"
        f"<td style='white-space:normal'>{html.escape(r.get('description',''))}</td>"
        f"<td style='color:#64748b'>{html.escape(r.get('timestamp',''))}</td>"
        f"</tr>"
    )


def generate(
    *,
    results_tsv: Path,
    report_dir: Path,
    title: str = "auto-cxas-scrapi Experiment Report",
) -> Path:
    """Generate an HTML report from results.tsv and return the output path."""
    report_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    if results_tsv.exists():
        with results_tsv.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))

    scores = [float(r["eval_score"]) for r in rows if "eval_score" in r]
    chart_svg = _svg_line_chart(scores)
    keep_rows = [r for r in rows if r.get("status") == "keep"]
    best = max(rows, key=lambda r: float(r.get("eval_score", 0))) if rows else None
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    sub = ""
    if best:
        sub = (
            f'<p class="sub">Best score: <strong>{float(best["eval_score"]):.6f}</strong> '
            f'({html.escape(best.get("commit",""))}) &nbsp;|&nbsp; '
            f'{len(rows)} experiments &nbsp;|&nbsp; {len(keep_rows)} improvements</p>'
        )

    rows_html = "\n".join(_row_html(r) for r in reversed(rows))

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{_STYLE}</style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  {sub}
  <p style="color:#64748b;font-size:.8rem">Generated: {generated_at}</p>
  <div class="chart">
    <h2>eval_score over experiments</h2>
    {chart_svg}
  </div>
  <table>
    <thead><tr>
      <th>commit</th><th>eval_score</th><th>task_success</th>
      <th>latency_p95</th><th>status</th><th>description</th><th>timestamp</th>
    </tr></thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"report_{stamp}.html"
    out.write_text(doc, encoding="utf-8")
    return out
