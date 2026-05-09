"""AIM v7.0 — Агенты"""
from .doctor import DoctorAgent
from .intake import IntakeAgent
from .lang import LangAgent

# Auto-register hook handlers (HW1, 2026-05-06) — connects HOOK_*
# producers to existing notify / escalation / db modules. Side-effect on
# import; bypass with AIM_NO_AUTO_HOOKS=1.
from . import hook_handlers as _hook_handlers  # noqa: F401

__all__ = ["DoctorAgent", "IntakeAgent", "LangAgent"]
