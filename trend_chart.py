#!/usr/bin/env python3
"""
Lab trend charts for AIM.
Generates PNG charts of lab parameter dynamics over time.

Usage:
  python3 trend_chart.py PATIENT_NAME PARAM       # single param
  python3 trend_chart.py PATIENT_NAME              # all params with history
  python3 trend_chart.py --list PATIENT_NAME       # list available params

Telegram bot command:  /trend ФАМИЛИЯ ПАРАМЕТР
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

AI_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AI_DIR)

import db as _db
from config import PATIENTS_DIR, get_logger

log = get_logger("trend_chart")


def find_patient_id(name_query: str) -> Optional[int]:
    """Find patient by partial name (surname or full name)."""
    rows = _db.search_patients(name_query)
    if not rows:
        return None
    return rows[0]["id"]


def get_param_history(patient_id: int, param: str) -> list[tuple[datetime, float, str]]:
    """
    Returns [(datetime, value, status), ...] sorted by date for one parameter.
    param: case-insensitive, e.g. "HGB", "hgb", "ТТГ"
    """
    history = _db.get_lab_history(patient_id)
    if not history:
        return []

    param_upper = param.upper()
    points = []
    for snap in history:
        params = snap.get("params", {})
        # Case-insensitive search
        for key, val in params.items():
            if key.upper() == param_upper:
                taken_at = snap.get("taken_at") or snap.get("date")
                try:
                    if isinstance(taken_at, str):
                        # Try multiple formats
                        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                dt = datetime.strptime(taken_at[:len(fmt)], fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            dt = datetime.fromisoformat(taken_at[:10])
                    else:
                        dt = taken_at or datetime.now()
                    numeric = float(val.get("value", val) if isinstance(val, dict) else val)
                    status = val.get("status", "normal") if isinstance(val, dict) else "normal"
                    points.append((dt, numeric, status))
                except (ValueError, TypeError):
                    continue
    return sorted(points, key=lambda x: x[0])


def list_patient_params(patient_id: int) -> list[str]:
    """List all parameters that have at least 2 data points."""
    history = _db.get_lab_history(patient_id)
    if not history:
        return []

    param_counts: dict[str, int] = {}
    for snap in history:
        for key in snap.get("params", {}).keys():
            param_counts[key] = param_counts.get(key, 0) + 1

    return sorted(k for k, cnt in param_counts.items() if cnt >= 2)


def make_chart(patient_id: int, param: str, output_path: str) -> Optional[str]:
    """
    Generate PNG trend chart for one lab parameter.
    Returns path to saved PNG or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        log.error("matplotlib not installed: pip install matplotlib")
        return None

    points = get_param_history(patient_id, param)
    if len(points) < 2:
        log.warning(f"Not enough data points for {param} (need ≥2, got {len(points)})")
        return None

    dates = [p[0] for p in points]
    values = [p[1] for p in points]
    statuses = [p[2] for p in points]

    # Colours by status
    colours = []
    for s in statuses:
        if s in ("high", "critical_high"):
            colours.append("#ff6b6b")
        elif s in ("low", "critical_low"):
            colours.append("#ffd93d")
        else:
            colours.append("#6bcb77")

    # ─── Plot ────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 4))
    fig.patch.set_facecolor("#0f1f3d")
    ax.set_facecolor("#0f1f3d")

    # Line
    ax.plot(dates, values, color="#c9a84c", linewidth=2, zorder=2)
    # Dots coloured by status
    for d, v, c in zip(dates, values, colours):
        ax.scatter(d, v, color=c, s=60, zorder=3)

    # Reference range (if available)
    try:
        from lab_reference import evaluate
        ref = evaluate(param, values[-1])
        if ref and ref.ref_min is not None and ref.ref_max is not None:
            ax.axhspan(ref.ref_min, ref.ref_max,
                       alpha=0.12, color="#6bcb77", label="Норма")
    except Exception:
        pass

    # Labels
    ax.set_title(f"Динамика: {param.upper()}", color="white", fontsize=13, pad=12)
    ax.set_xlabel("Дата", color="#aaa", fontsize=10)
    ax.tick_params(colors="white", labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334466")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30)

    # Value labels on points
    for d, v in zip(dates, values):
        ax.annotate(f"{v:.1f}", (d, v),
                    textcoords="offset points", xytext=(0, 10),
                    fontsize=8, color="white", ha="center")

    ax.legend(facecolor="#0f2a4a", labelcolor="white", fontsize=8)
    plt.tight_layout()

    try:
        fig.savefig(output_path, dpi=150, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        log.info(f"Chart saved: {output_path}")
        return output_path
    except Exception as e:
        log.error(f"Failed to save chart: {e}")
        plt.close(fig)
        return None


def make_chart_tempfile(patient_id: int, param: str) -> Optional[str]:
    """Generate chart to a temp file. Returns path or None."""
    import tempfile
    tmp = tempfile.mktemp(suffix=f"_{param.upper()}.png", prefix="aim_trend_")
    os.chmod(os.path.dirname(tmp) if os.path.dirname(tmp) else "/tmp", 0o700)
    return make_chart(patient_id, param, tmp)


def make_all_charts(patient_id: int, output_dir: str) -> list[str]:
    """Generate charts for all params with ≥2 data points. Returns list of PNG paths."""
    params = list_patient_params(patient_id)
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for param in params:
        out = os.path.join(output_dir, f"trend_{param.upper()}.png")
        result = make_chart(patient_id, param, out)
        if result:
            paths.append(result)
    return paths


# ─── CLI ─────────────────────────────────────────────────────────

def _usage():
    print("Usage:")
    print("  python3 trend_chart.py PATIENT_NAME PARAM     — chart for one param")
    print("  python3 trend_chart.py PATIENT_NAME           — all params")
    print("  python3 trend_chart.py --list PATIENT_NAME    — list available params")
    sys.exit(1)


if __name__ == "__main__":
    _db.init_db()

    args = sys.argv[1:]
    if not args:
        _usage()

    if args[0] == "--list":
        if len(args) < 2:
            _usage()
        name_q = " ".join(args[1:])
        pid = find_patient_id(name_q)
        if not pid:
            print(f"Patient not found: {name_q}")
            sys.exit(1)
        params = list_patient_params(pid)
        if params:
            print(f"Params with ≥2 points: {', '.join(params)}")
        else:
            print("No multi-point data found.")
        sys.exit(0)

    if len(args) == 1:
        name_q = args[0]
        pid = find_patient_id(name_q)
        if not pid:
            print(f"Patient not found: {name_q}")
            sys.exit(1)
        out_dir = f"/tmp/aim_trends_{pid}"
        paths = make_all_charts(pid, out_dir)
        print(f"Generated {len(paths)} chart(s) in {out_dir}")
        for p in paths:
            print(f"  {p}")
        sys.exit(0)

    if len(args) >= 2:
        name_q = args[0]
        param = args[1]
        pid = find_patient_id(name_q)
        if not pid:
            print(f"Patient not found: {name_q}")
            sys.exit(1)
        out = f"/tmp/aim_trend_{pid}_{param.upper()}.png"
        result = make_chart(pid, param, out)
        if result:
            print(f"Chart saved: {result}")
        else:
            print(f"Could not generate chart for {param}")
        sys.exit(0)

    _usage()
