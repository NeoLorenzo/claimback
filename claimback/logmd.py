"""Render a run's agent log (and the case opened from it) as one Markdown file.

  python -m claimback.logmd <run_id> [--case <case_id>] [--out agent-logs.md]

Same content as events.jsonl: placeholders and counts only, never identifiers."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from . import trace
from .export import _case_for, _scrubber
from .state import RUNS_DIR

ICON = {"start": "▶", "done": "✓", "handoff": "→", "retry": "↻", "error": "✗", "loop": "⟲", "warn": "!", "info": "·"}
DETAIL_KINDS = {"done", "retry", "error", "handoff", "loop"}


def _section(title: str, events: list[dict]) -> list[str]:
    if not events:
        return []
    t0 = datetime.fromisoformat(events[0]["ts"])
    out = [f"## {title}", "", f"{len(events)} events, starting {t0:%Y-%m-%d %H:%M:%S} UTC.", ""]
    for e in events:
        secs = (datetime.fromisoformat(e["ts"]) - t0).total_seconds()
        stamp = f"{int(secs // 60)}:{int(secs % 60):02d}"
        out.append(f"- `{stamp}` **{e['agent']}** {ICON.get(e['kind'], '·')} {e['message']}")
        d = {k: v for k, v in (e.get("data") or {}).items() if k not in ("case",)}
        if e["kind"] in DETAIL_KINDS and d:
            out += ["", "  <details><summary>data</summary>", "", "  ```json"]
            out += ["  " + line for line in json.dumps(d, indent=2, ensure_ascii=False).splitlines()]
            out += ["  ```", "", "  </details>", ""]
    out.append("")
    return out


def _totals(label: str, events: list[dict]) -> list[str]:
    t = trace.totals(events)
    if not events:
        return []
    span = (datetime.fromisoformat(events[-1]["ts"]) - datetime.fromisoformat(events[0]["ts"])).total_seconds()
    rows = [f"| {label} | {span / 60:.1f} min | {t['model_calls']} | {t['input_tokens']:,} / {t['output_tokens']:,} | "
            f"${t['cost_usd']:.2f} | {t['retries']} |"]
    return rows


def render(run_id: str, case_id: str | None = None) -> str:
    scrub = _scrubber()
    run_events = [scrub(json.loads(l)) for l in (RUNS_DIR / run_id / "events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    cdir = _case_for(run_id, case_id)
    case_events = [scrub(json.loads(l)) for l in (cdir / "events.jsonl").read_text(encoding="utf-8").splitlines()
                   if l.strip()] if cdir else []
    lines = [f"# ClaimBack agent logs: run `{run_id}`" + (f" and case `{cdir.name}`" if cdir else ""), "",
             "Recorded from ClaimBack's real event logs (`events.jsonl`). Synthetic patient; the insurer's emails are "
             "SIMULATED by a scripted test harness. Logs contain placeholders such as `[PATIENT_NAME_1]` and counts, "
             "never identifiers. Model calls show model, effort, tokens, time and estimated list-price cost.", "",
             "| Phase | Wall time | Model calls | Tokens in / out | Est. cost | Retries |", "|---|---|---|---|---|---|"]
    lines += _totals("Agent run", run_events) + _totals("Case with the insurer", case_events)
    lines += ["", "Legend: ▶ start · ✓ done · → handoff · ↻ retry (reason and what was fed back) · ⟲ revision loop · "
              "! warning · ✗ error · `m:ss` since the phase started.", ""]
    lines += _section("Phase 1 · Agent run", run_events)
    lines += _section("Phase 2 · Case with the insurer", case_events)
    return "\n".join(lines)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run_id")
    p.add_argument("--case")
    p.add_argument("--out", type=Path, default=Path("agent-logs.md"))
    a = p.parse_args()
    a.out.write_text(render(a.run_id, a.case), encoding="utf-8")
    print(f"wrote {a.out}")
