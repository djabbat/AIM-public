"""agents/pi_agent.py — Personal Intelligence Agent (background helper).

Watches AIM usage, learns frequency/time patterns, proactively suggests next
actions, and (in `auto` mode) periodically organises memory by theme.

Modes:
    suggest-only       — observation + suggestions; no mutating actions
    auto               — also runs nightly memory organisation at 03:00 local

History store: ~/.claude/pi_history.json
Learning is opt-in: hook `pi.learn(task, result, duration)` after run_agent().
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("aim.pi")

HIST_PATH = Path("~/.claude/pi_history.json").expanduser()
ENABLED   = os.getenv("AIM_PI_ENABLED", "").lower() in ("1", "true", "yes")
MODE      = os.getenv("AIM_PI_MODE", "suggest-only")   # suggest-only | auto

# Heuristic task classifier — cheap, no LLM call
_KEYWORDS = {
    "coding":      ("код", "напиши", "функция", "класс", "debug", "исправь", "patch", "implement"),
    "research":    ("найди", "поищи", "исследование", "статья", "pubmed", "doi", "review"),
    "memory":      ("запомни", "помни", "не забывай", "memory", "remember", "recall"),
    "analysis":    ("анализ", "проанализируй", "сравни", "оцени", "audit"),
    "translation": ("переведи", "translate", "перевод"),
    "writing":     ("напиши письмо", "draft", "email", "ответь", "respond"),
    "planning":    ("план", "roadmap", "стратегия", "deadline"),
}


def _classify(text: str) -> str:
    t = text.lower()
    for cat, kws in _KEYWORDS.items():
        if any(k in t for k in kws):
            return cat
    return "general"


# ── PI Agent ────────────────────────────────────────────────────────────────


class PersonalIntelligenceAgent:
    def __init__(self, history_path: Path = HIST_PATH) -> None:
        self.path = history_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self.running = False
        self._stop = threading.Event()

    # ── persistence ────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"tasks": [], "patterns": {}, "time_based": {}}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # ── observation ────────────────────────────────────────────────────────

    def learn(self, task: str, result: str = "", duration: float = 0.0) -> None:
        if not task:
            return
        cat = _classify(task)
        ts = datetime.now()
        rec = {
            "task":      task[:300],
            "category":  cat,
            "duration":  round(duration, 2),
            "timestamp": ts.isoformat(timespec="seconds"),
            "hour":      ts.hour,
            "weekday":   ts.weekday(),
        }
        self.data["tasks"].append(rec)
        if len(self.data["tasks"]) > 1000:
            self.data["tasks"] = self.data["tasks"][-500:]

        h = str(ts.hour)
        self.data.setdefault("time_based", {}).setdefault(h, [])
        self.data["time_based"][h].append(task[:80])
        self.data["time_based"][h] = self.data["time_based"][h][-30:]   # cap

        self.data.setdefault("patterns", {}).setdefault(cat, 0)
        self.data["patterns"][cat] += 1

        self._save()

    # ── suggestions ────────────────────────────────────────────────────────

    def suggest(self) -> list[dict]:
        """Return a small list of proactive hints based on past behaviour."""
        out: list[dict] = []
        now = datetime.now()
        h = str(now.hour)

        # 1. Time-of-day pattern
        same_hour = self.data.get("time_based", {}).get(h, [])
        if len(same_hour) >= 3:
            common = Counter(same_hour).most_common(3)
            out.append({
                "type": "time-of-day",
                "msg":  f"в {now.hour:02d}:00 ты обычно делаешь: " +
                        ", ".join(f"{t!r}×{c}" for t, c in common),
            })

        # 2. Frequent category
        recent = self.data["tasks"][-50:]
        cats = Counter(r["category"] for r in recent)
        if cats:
            top, n = cats.most_common(1)[0]
            if n >= 5:
                out.append({
                    "type": "frequent-category",
                    "msg":  f"за последние {len(recent)} задач: '{top}' встречалось {n} раз. "
                            f"возможно, нужен шаблон / preset?",
                })

        # 3. Long-running tasks
        slow = [r for r in recent if r["duration"] > 30]
        if len(slow) >= 3:
            out.append({
                "type": "slow-tasks",
                "msg":  f"{len(slow)} задач из последних {len(recent)} заняли >30s. "
                        f"проверь circuit breaker / включи cache (AIM_LLM_CACHE=1)?",
            })

        # 4. Forgotten pattern (something you did before, not in last 7 days)
        cutoff = (now - timedelta(days=7)).isoformat()
        old = [r for r in self.data["tasks"] if r["timestamp"] < cutoff]
        new = [r for r in self.data["tasks"] if r["timestamp"] >= cutoff]
        old_cats = set(r["category"] for r in old) - set(r["category"] for r in new)
        if old_cats:
            out.append({
                "type": "missed-category",
                "msg":  f"за последнюю неделю не было: {', '.join(sorted(old_cats))} — намеренно?",
            })
        return out

    # ── auto-organisation (nightly) ────────────────────────────────────────

    def organise_memory(self) -> dict:
        """Produce a per-theme index in user_memories/auto_index/<theme>.md.

        Doesn't move existing facts; only creates a summary index that helps
        humans browse by category. Idempotent (overwrites the index file).
        """
        try:
            from agents.memory_store import USER_MEMORIES, remember
        except Exception as e:
            log.warning(f"organise_memory unavailable: {e}")
            return {"error": str(e)}

        if not USER_MEMORIES.exists():
            return {"skipped": "no user_memories dir"}

        # group by category dir
        by_cat: dict[str, list[Path]] = defaultdict(list)
        for cat_dir in USER_MEMORIES.iterdir():
            if not cat_dir.is_dir() or cat_dir.name == "auto_index":
                continue
            for f in cat_dir.glob("*.md"):
                by_cat[cat_dir.name].append(f)

        written: dict[str, int] = {}
        for cat, files in by_cat.items():
            if len(files) < 5:
                continue
            lines = [f"# auto-index: {cat} ({len(files)} facts)",
                     f"updated: {datetime.now().isoformat(timespec='seconds')}",
                     ""]
            for f in sorted(files, key=lambda p: -p.stat().st_mtime)[:30]:
                first_line = ""
                try:
                    body = f.read_text(encoding="utf-8")
                    body = re.sub(r"^---.*?---", "", body, count=1, flags=re.DOTALL).strip()
                    first_line = body.splitlines()[0] if body else ""
                except Exception:
                    pass
                lines.append(f"- **{f.name}** — {first_line[:140]}")
            remember("\n".join(lines), category="auto_index", quiet=True,
                     metadata={"theme": cat, "count": len(files)})
            written[cat] = len(files)
        return {"organised": written}

    # ── background loop ────────────────────────────────────────────────────

    async def run_background(self, interval_s: int = 300, do_organise: bool = True) -> None:
        self.running = True
        last_organise_day: Any = None
        while self.running and not self._stop.is_set():
            try:
                tips = self.suggest()
                if tips and datetime.now().hour in (9, 14, 18):
                    log.info("[pi] suggestions: " + "; ".join(t["msg"] for t in tips))

                today = datetime.now().date()
                if do_organise and datetime.now().hour == 3 and today != last_organise_day:
                    res = self.organise_memory()
                    log.info(f"[pi] auto-organise: {res}")
                    last_organise_day = today
            except Exception as e:
                log.warning(f"[pi] loop error: {e}")
            await asyncio.sleep(interval_s)

    def stop(self) -> None:
        self.running = False
        self._stop.set()

    # ── stats ──────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        if not self.data["tasks"]:
            return {"tasks": 0}
        recent = self.data["tasks"][-200:]
        cats = Counter(r["category"] for r in recent)
        return {
            "tasks_total":  len(self.data["tasks"]),
            "tasks_recent": len(recent),
            "categories":   dict(cats.most_common()),
            "avg_duration": round(sum(r["duration"] for r in recent) / max(len(recent), 1), 2),
            "history_path": str(self.path),
        }


# ── module-level singleton ─────────────────────────────────────────────────


_INSTANCE: PersonalIntelligenceAgent | None = None


def get_pi() -> PersonalIntelligenceAgent:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PersonalIntelligenceAgent()
    return _INSTANCE


def maybe_learn(task: str, result: str = "", duration: float = 0.0) -> None:
    """Safe no-op when AIM_PI_ENABLED is not set."""
    if not ENABLED:
        return
    try:
        get_pi().learn(task, result, duration)
    except Exception as e:
        log.debug(f"learn failed: {e}")


# ── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-pi")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("suggest")
    sub.add_parser("organise")
    sub.add_parser("stats")
    sub.add_parser("learn-cli", help="manually log a task: usage `learn-cli '<task>' --duration 5`")
    learn = sub.add_parser("learn")
    learn.add_argument("task")
    learn.add_argument("--duration", type=float, default=0.0)
    sub.add_parser("clear")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    pi = get_pi()
    if args.cmd == "status":
        print(json.dumps({"enabled": ENABLED, "mode": MODE, **pi.stats()},
                         ensure_ascii=False, indent=2))
    elif args.cmd == "suggest":
        for s in pi.suggest():
            print(f"💡 [{s['type']}] {s['msg']}")
    elif args.cmd == "organise":
        print(json.dumps(pi.organise_memory(), ensure_ascii=False, indent=2))
    elif args.cmd == "stats":
        print(json.dumps(pi.stats(), ensure_ascii=False, indent=2))
    elif args.cmd == "learn":
        pi.learn(args.task, "", args.duration)
        print("logged")
    elif args.cmd == "clear":
        pi.path.unlink(missing_ok=True)
        print("cleared")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
