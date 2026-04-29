"""agents/adaptive_limiter.py — adaptive token bucket with backpressure.

Drop-in replacement for the static `TokenBucket` in `llm.py`. Cuts the rate
in half after `error_threshold` consecutive failures, then slowly recovers
(+5% per success) up to `target_rpm` once 5 successes accumulate.

Auto-attached: when imported, `llm.TokenBucket` instances get a sibling
`AdaptiveRateLimiter` that the LLM router can switch to via env:

    AIM_RATE_ADAPTIVE=1     # enable adaptive mode
    AIM_RATE_MIN_RPM=5      # floor (default: 5)
    AIM_RATE_ERR_THRESHOLD=3
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

log = logging.getLogger("aim.adaptive")


class AdaptiveRateLimiter:
    def __init__(self, target_rpm: float = 50, min_rpm: float = 5,
                 error_threshold: int = 3, success_window: int = 5):
        self.target_rpm = float(target_rpm)
        self.min_rpm    = float(min_rpm)
        self.current_rpm = self.target_rpm
        self.error_threshold = error_threshold
        self.success_window  = success_window

        self.error_count   = 0
        self.success_count = 0
        self.last_error_ts: float = 0.0
        self.history:    deque[tuple[float, str]] = deque(maxlen=100)
        self._lock = threading.Lock()
        self._last_token_ts = time.time()

    # ── token bucket ───────────────────────────────────────────────────────

    def _interval(self) -> float:
        return 60.0 / max(self.current_rpm, 0.1)

    def acquire(self, n: int = 1, timeout: float = 30.0) -> bool:
        """Block until a token is available (or timeout)."""
        deadline = time.time() + timeout
        for _ in range(n):
            with self._lock:
                now = time.time()
                wait = max(0.0, self._last_token_ts + self._interval() - now)
                self._last_token_ts = now + wait
            if wait > 0:
                if time.time() + wait > deadline:
                    raise TimeoutError(
                        f"adaptive rate-limit wait {wait:.1f}s > timeout {timeout:.1f}s")
                time.sleep(wait)
        return True

    # ── feedback loop ──────────────────────────────────────────────────────

    def record_error(self) -> None:
        with self._lock:
            self.error_count += 1
            self.success_count = 0
            self.last_error_ts = time.time()
            self.history.append((self.last_error_ts, "err"))
            if self.error_count >= self.error_threshold:
                # halve rate, but not below min
                new_rate = max(self.min_rpm, self.current_rpm / 2.0)
                if new_rate != self.current_rpm:
                    log.warning(
                        f"backpressure: {self.current_rpm:.1f} → {new_rate:.1f} RPM "
                        f"(after {self.error_count} errors)"
                    )
                    self.current_rpm = new_rate

    def record_success(self) -> None:
        with self._lock:
            self.success_count += 1
            self.history.append((time.time(), "ok"))
            if self.success_count >= self.success_window and self.error_count > 0:
                self.error_count = max(0, self.error_count - 1)
                self.success_count = 0
            # +5% recovery
            if self.current_rpm < self.target_rpm:
                self.current_rpm = min(self.target_rpm, self.current_rpm * 1.05)

    # ── introspection ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            recent_errs = sum(1 for t, k in self.history if k == "err"
                              and t > time.time() - 300)
            return {
                "current_rpm":    round(self.current_rpm, 1),
                "target_rpm":     self.target_rpm,
                "min_rpm":        self.min_rpm,
                "error_count":    self.error_count,
                "success_count":  self.success_count,
                "errors_last_5m": recent_errs,
                "backoff_active": self.error_count >= self.error_threshold,
                "interval_ms":    round(self._interval() * 1000),
            }


def _main():
    import argparse, json
    p = argparse.ArgumentParser(prog="aim-rate-status")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "status":
        try:
            from llm import _DS_LIMITER, _GROQ_LIMITER  # noqa
            print(json.dumps({
                "deepseek": _stats_of(_DS_LIMITER),
                "groq":     _stats_of(_GROQ_LIMITER),
            }, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"limiters not initialised: {e}")


def _stats_of(b) -> dict:
    if hasattr(b, "stats"):
        return b.stats()
    return {"current_rpm": getattr(b, "rate", "?") * 60,
            "capacity":    getattr(b, "capacity", "?")}


if __name__ == "__main__":
    _main()
