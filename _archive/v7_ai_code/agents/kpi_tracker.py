"""agents/kpi_tracker.py — per-project KPI tracking (K1, 2026-05-03).

Project YAMLs may declare a `kpis:` block:

    kpis:
      - id: pubmed-publications
        target: 8
        unit: count
        history:
          - {date: 2026-04-01, value: 5}
          - {date: 2026-05-01, value: 7}
      - id: eic-loi-signed
        target: 2
        unit: count
        history:
          - {date: 2026-05-03, value: 1}
      - id: weekly-llm-cost
        target: 25.0
        target_kind: ceiling   # default = floor (we want value >= target)
        unit: usd
        history: []

This module:
  * loads the kpis section
  * computes progress (current / target, with ceiling logic when needed)
  * emits a dashboard string for inclusion in morning_brief
  * supports `record(project, kpi_id, value, date=...)` to append history
    points (writes back to the YAML)
  * reports week-over-week velocity for floor-kind KPIs

Public API:
    load(project) -> list[KPI]
    record(project, kpi_id, value, date=None) -> None
    summary(project) -> str
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.kpi")


@dataclasses.dataclass
class KPIPoint:
    date: dt.date
    value: float

    def to_yaml(self) -> dict:
        return {"date": self.date.isoformat(), "value": self.value}


@dataclasses.dataclass
class KPI:
    id: str
    target: float
    unit: str = ""
    target_kind: str = "floor"   # floor | ceiling
    history: list[KPIPoint] = dataclasses.field(default_factory=list)

    @property
    def current(self) -> Optional[float]:
        if not self.history:
            return None
        # Latest by date.
        return sorted(self.history, key=lambda p: p.date)[-1].value

    @property
    def progress(self) -> Optional[float]:
        cur = self.current
        if cur is None or self.target == 0:
            return None
        if self.target_kind == "ceiling":
            # Lower is better. progress goes 1.0 → 0 as we breach.
            return max(0.0, 1.0 - max(0.0, cur - self.target) / abs(self.target))
        return cur / self.target

    @property
    def status(self) -> str:
        cur = self.current
        if cur is None or self.target == 0:
            return "unknown"
        if self.target_kind == "ceiling":
            util = cur / self.target
            if util > 1.0:
                return "breach"
            if util >= 0.85:
                return "warn"
            return "ok"
        p = cur / self.target
        return ("met" if p >= 1.0 else "near" if p >= 0.85 else "behind")

    def velocity_per_week(self) -> Optional[float]:
        """Average rate of change per week across history (floor KPIs only)."""
        if len(self.history) < 2:
            return None
        h = sorted(self.history, key=lambda p: p.date)
        d_value = h[-1].value - h[0].value
        d_days = (h[-1].date - h[0].date).days
        if d_days <= 0:
            return None
        return d_value / (d_days / 7.0)


# ── persistence ──────────────────────────────────────────────────


def _project_path(project: str) -> Path:
    from agents import project_owner as po
    return po.projects_dir() / f"{project}.yaml"


def _parse_point(raw: dict) -> Optional[KPIPoint]:
    d = raw.get("date")
    if isinstance(d, dt.date):
        date = d
    elif isinstance(d, str):
        try:
            date = dt.date.fromisoformat(d[:10])
        except ValueError:
            return None
    else:
        return None
    try:
        v = float(raw.get("value"))
    except (TypeError, ValueError):
        return None
    return KPIPoint(date=date, value=v)


def load(project: str) -> list[KPI]:
    import yaml
    path = _project_path(project)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[KPI] = []
    for k in raw.get("kpis") or []:
        try:
            target = float(k.get("target"))
        except (TypeError, ValueError):
            log.warning("kpi %s in %s: target not numeric — skipped",
                        k.get("id"), project)
            continue
        history = []
        for p in k.get("history") or []:
            pt = _parse_point(p)
            if pt is not None:
                history.append(pt)
        out.append(KPI(
            id=str(k.get("id", "")),
            target=target,
            unit=str(k.get("unit", "")),
            target_kind=str(k.get("target_kind", "floor")),
            history=history,
        ))
    return out


def record(project: str, kpi_id: str, value: float,
           date: Optional[dt.date] = None) -> None:
    """Append a (date, value) point to the named KPI in the YAML."""
    import yaml
    path = _project_path(project)
    if not path.exists():
        raise FileNotFoundError(f"no project YAML at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    kpis = raw.get("kpis") or []
    target_kpi = None
    for k in kpis:
        if str(k.get("id")) == kpi_id:
            target_kpi = k
            break
    if target_kpi is None:
        raise KeyError(f"KPI {kpi_id!r} not declared in {project}")
    history = list(target_kpi.get("history") or [])
    history.append({"date": (date or dt.date.today()).isoformat(),
                    "value": float(value)})
    target_kpi["history"] = history
    raw["kpis"] = kpis
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


# ── presentation ─────────────────────────────────────────────────


def _bar(progress: float, width: int = 16) -> str:
    if progress is None or progress < 0:
        return "(?)"
    p = min(1.0, max(0.0, progress))
    filled = int(round(p * width))
    return "[" + "█" * filled + "·" * (width - filled) + "]"


def summary(project: str) -> str:
    kpis = load(project)
    if not kpis:
        return ""
    lines = [f"📈 KPIs — {project}"]
    for k in kpis:
        cur = k.current
        cur_str = "—" if cur is None else f"{cur:g}{k.unit}"
        target_str = f"{k.target:g}{k.unit}"
        bar = _bar(k.progress) if k.progress is not None else "(no data)"
        v = k.velocity_per_week()
        v_str = f"  +{v:.1f}/w" if v and v > 0 else (f"  {v:.1f}/w" if v else "")
        lines.append(f"  • {k.id}: {cur_str} / {target_str}  "
                     f"{bar} {k.status}{v_str}")
    return "\n".join(lines)
