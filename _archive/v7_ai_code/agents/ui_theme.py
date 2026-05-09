"""
AIM UI theme — Claude Code-inspired CLI palette, inverted to a cool/cyan gamma.

Claude Code uses warm accents (orange/amber) on dark. AIM inverts hue 180° → cool
cyan/blue accents. Other axes (success/danger/dim) stay at standard cool colors.

Usage in CLI/agent code:

    from agents.ui_theme import ui, Console

    ui.banner("AIM v7.0")               # title panel with cyan border
    ui.user("Какие препараты несовместимы?")
    ui.assistant("Симвастатин + кларитромицин: ингибитор CYP3A4 …")
    ui.tool_call("interactions.check_pair", "симвастатин, кларитромицин")
    with ui.spinner("DeepSeek-v4-pro thinking…"):
        ...
    ui.success("Отчёт сохранён → reports/case_42.pdf")
    ui.warning("Глюкоза > верхнего критического (H2)")
    ui.error("DeepSeek API недоступен, fallback → Groq")
    ui.info("Pacient_id=42, lang=ru")
    ui.process("intake.ocr", duration=4.2)   # one-line process indicator
    ui.divider()
    ui.kv({"Patient": "Иванова Е.И.", "Age": 67, "Lang": "ru"})

If `rich` is unavailable, falls back to plain print with no styling — never crashes.
"""

from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Iterable

# ── PALETTE ────────────────────────────────────────────────────────────────────
# Tuned to invert Claude Code's warm palette while keeping universal axes.
# Hex chosen for contrast on a dark terminal background (≥7:1 vs #0A0F1E).
class Theme:
    BG          = "#0A0F1E"   # deep navy (typical terminal already dark; used in panels)
    SURFACE     = "#16213E"   # surface panel background
    BORDER      = "#1F3A68"   # quiet blue border

    # Primary cool accent (replaces Claude Code's orange)
    PRIMARY     = "#00D9FF"   # bright cyan — main brand
    PRIMARY_DIM = "#0099BB"   # darker cyan for non-interactive accents
    ACCENT      = "#4A9EFF"   # secondary blue
    HIGHLIGHT   = "#80E5FF"   # light cyan highlight (selection / focus)

    # Universal status axes (no inversion — these are already cool/standard)
    SUCCESS     = "#4AFF91"   # bright green
    WARNING     = "#80B0FF"   # blue-leaning amber (intentionally muted, not yellow)
    DANGER      = "#FF6B8A"   # red with violet tint, not pure red
    INFO        = "#A6C8FF"   # soft blue

    # Text
    TEXT        = "#E8F0FF"   # near-white with cool tint
    DIM         = "#7A8AA0"   # muted gray-blue (replaces Claude Code's gray)
    SUBTLE      = "#54657A"   # very muted (timestamps, ids)

    # Roles in chat
    USER        = "#80E5FF"   # cyan — user echoes
    ASSISTANT   = "#E8F0FF"   # near-white — main response body
    SYSTEM      = "#7A8AA0"   # dim — system notes
    TOOL        = "#4A9EFF"   # blue — tool call labels
    PROCESS     = "#00D9FF"   # cyan — running processes (spinners, etc.)


T = Theme  # alias


# ── ICONS ──────────────────────────────────────────────────────────────────────
class Icon:
    USER       = "›"
    ASSISTANT  = "✦"
    TOOL       = "⚙"
    PROCESS    = "⟳"
    SUCCESS    = "✓"
    WARNING    = "⚠"
    ERROR      = "✗"
    INFO       = "ℹ"
    BULLET     = "•"
    ARROW_R    = "→"
    DIVIDER    = "─"


# ── RICH adapter (graceful fallback) ───────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich.markdown import Markdown
    from rich.spinner import Spinner
    from rich.live import Live
    from rich.rule import Rule
    from rich.theme import Theme as RichTheme
    _HAS_RICH = True
except Exception:
    _HAS_RICH = False
    Console = None  # type: ignore


# Rich Theme — semantic style names that map to palette
_RICH_STYLES = {
    "primary":   T.PRIMARY,
    "accent":    T.ACCENT,
    "highlight": T.HIGHLIGHT,
    "success":   T.SUCCESS,
    "warning":   T.WARNING,
    "danger":    T.DANGER,
    "info":      T.INFO,
    "dim":       T.DIM,
    "subtle":    T.SUBTLE,
    "text":      T.TEXT,
    "user":      T.USER,
    "assistant": T.ASSISTANT,
    "system":    T.SYSTEM,
    "tool":      f"bold {T.TOOL}",
    "process":   f"bold {T.PROCESS}",
}


class UI:
    """Single entry point for AIM CLI styling.

    Constructed once (module-level `ui`) and shared across the codebase.
    """

    def __init__(self) -> None:
        if _HAS_RICH:
            self.console = Console(theme=RichTheme(_RICH_STYLES), highlight=False)
        else:
            self.console = None

    # ── Plain helpers (no-op if rich missing) ─────────────────────────────────
    def _print(self, *args, style: str | None = None, **kw) -> None:
        if self.console is not None:
            self.console.print(*args, style=style, **kw)
        else:
            print(*args)

    # ── Headers ───────────────────────────────────────────────────────────────
    def banner(self, title: str, subtitle: str | None = None) -> None:
        if self.console:
            inner = Text(title, style=f"bold {T.PRIMARY}")
            if subtitle:
                inner.append("\n")
                inner.append(subtitle, style=T.DIM)
            self.console.print(Panel(
                inner, border_style=T.PRIMARY, padding=(0, 2),
            ))
        else:
            print(f"\n=== {title} ===")
            if subtitle:
                print(subtitle)

    def divider(self, label: str | None = None) -> None:
        if self.console:
            self.console.print(Rule(label or "", style=T.BORDER))
        else:
            print("─" * 60)

    # ── Roles in chat ─────────────────────────────────────────────────────────
    def user(self, msg: str) -> None:
        if self.console:
            self.console.print(f"[user]{Icon.USER}[/]  [user]{msg}[/]")
        else:
            print(f"{Icon.USER} {msg}")

    def assistant(self, msg: str, *, markdown: bool = False) -> None:
        if self.console:
            head = Text(f"{Icon.ASSISTANT}  ", style=f"bold {T.PRIMARY}")
            self.console.print(head, end="")
            if markdown:
                self.console.print(Markdown(msg, code_theme="monokai"))
            else:
                self.console.print(msg, style="assistant")
        else:
            print(f"{Icon.ASSISTANT}  {msg}")

    def system(self, msg: str) -> None:
        self._print(f"[system]{Icon.BULLET} {msg}[/]")

    # ── Tool calls (Claude Code style) ────────────────────────────────────────
    def tool_call(self, name: str, args: str | dict | None = None) -> None:
        if self.console:
            label = Text(f" {Icon.TOOL} ", style=f"reverse {T.TOOL}")
            body = Text(name, style=f"bold {T.TOOL}")
            line = Text.assemble(label, " ", body)
            if args:
                arg_repr = args if isinstance(args, str) else str(args)
                if len(arg_repr) > 100:
                    arg_repr = arg_repr[:97] + "..."
                line.append(f"  {arg_repr}", style=T.DIM)
            self.console.print(line)
        else:
            print(f"[{Icon.TOOL}] {name} {args or ''}")

    def tool_result(self, summary: str) -> None:
        self._print(f"  [dim]{Icon.ARROW_R}[/] [success]{summary}[/]")

    # ── Process indicators ────────────────────────────────────────────────────
    def process(self, label: str, *, duration: float | None = None,
                detail: str | None = None) -> None:
        """One-line summary of a completed process step."""
        if self.console:
            line = Text.assemble(
                ("  ", ""),
                (Icon.PROCESS, f"bold {T.PROCESS}"),
                ("  ", ""),
                (label, "process"),
            )
            if duration is not None:
                line.append(f"  ({duration:.1f}s)", style=T.SUBTLE)
            if detail:
                line.append(f"  {detail}", style=T.DIM)
            self.console.print(line)
        else:
            d = f" ({duration:.1f}s)" if duration is not None else ""
            print(f"  {Icon.PROCESS}  {label}{d}")

    @contextmanager
    def spinner(self, label: str):
        """Live spinner for long-running operations.

        Usage:
            with ui.spinner("DeepSeek thinking..."):
                result = ask_deep(prompt)
        """
        if self.console:
            spin = Spinner("dots", text=Text(label, style="process"), style=T.PROCESS)
            with Live(spin, console=self.console, transient=True, refresh_per_second=12):
                yield
        else:
            print(f"  {Icon.PROCESS} {label}...")
            yield

    # ── Status messages ───────────────────────────────────────────────────────
    def success(self, msg: str) -> None:
        self._print(f"[success]{Icon.SUCCESS}[/]  [success]{msg}[/]")

    def warning(self, msg: str) -> None:
        self._print(f"[warning]{Icon.WARNING}[/]  [warning]{msg}[/]")

    def error(self, msg: str) -> None:
        self._print(f"[danger]{Icon.ERROR}[/]  [danger]{msg}[/]")

    def info(self, msg: str) -> None:
        self._print(f"[info]{Icon.INFO}[/]  [info]{msg}[/]")

    # ── Structured output ─────────────────────────────────────────────────────
    def kv(self, mapping: dict[str, Any], *, title: str | None = None) -> None:
        """Compact key-value table."""
        if self.console:
            t = Table(show_header=False, show_edge=False, box=None,
                      padding=(0, 2, 0, 0))
            t.add_column(style="dim", justify="right")
            t.add_column(style="text")
            for k, v in mapping.items():
                t.add_row(str(k), str(v))
            if title:
                self.console.print(Panel(t, title=title, border_style=T.BORDER,
                                          title_align="left"))
            else:
                self.console.print(t)
        else:
            for k, v in mapping.items():
                print(f"  {k}: {v}")

    def table(self, columns: list[str], rows: Iterable[Iterable[Any]], *,
              title: str | None = None) -> None:
        if self.console:
            t = Table(title=title, border_style=T.BORDER,
                      header_style=f"bold {T.PRIMARY}",
                      title_style=f"bold {T.PRIMARY}")
            for c in columns:
                t.add_column(c)
            for r in rows:
                t.add_row(*[str(x) for x in r])
            self.console.print(t)
        else:
            print(" | ".join(columns))
            for r in rows:
                print(" | ".join(str(x) for x in r))

    def panel(self, body: str, *, title: str | None = None,
              style: str = "primary") -> None:
        if self.console:
            color = _RICH_STYLES.get(style, T.PRIMARY)
            self.console.print(Panel(body, title=title, border_style=color,
                                     title_align="left"))
        else:
            if title:
                print(f"\n--- {title} ---")
            print(body)

    def md(self, markdown_text: str) -> None:
        if self.console:
            self.console.print(Markdown(markdown_text, code_theme="monokai"))
        else:
            print(markdown_text)


# ── Module-level singleton ─────────────────────────────────────────────────────
ui = UI()


def install_global_console() -> None:
    """Replace builtins.print with Rich's themed console.print.

    Call this ONCE at the AIM CLI startup (e.g. in medical_system.py top-level
    or aim.__main__). Effect: every plain `print()` call across all loaded
    modules — including agents/* — gets Rich's automatic syntax highlighting
    (numbers, strings, paths, URLs) and respects the cool/cyan AIM theme.

    Existing semantic helpers (ui.success/warning/error/spinner/etc.) keep
    working unchanged. Calling install() twice is a no-op.

    Disable via `AIM_NO_RICH=1` env (e.g. for piped/CI output).
    """
    import os, builtins
    if getattr(install_global_console, "_installed", False):
        return
    if os.getenv("AIM_NO_RICH", "").lower() in ("1", "true", "yes"):
        return
    if not _HAS_RICH or ui.console is None:
        return
    # Wrap so we accept the standard print signature transparently.
    _orig = builtins.print
    def _themed_print(*args, sep=" ", end="\n", file=None, flush=False):
        # Rich's console.print honours sep/end natively for strings; for
        # non-string args it calls __repr__ with highlighting.
        try:
            ui.console.print(*args, sep=sep, end=end)
        except Exception:
            # Never break the host program — fall back to original print.
            _orig(*args, sep=sep, end=end, file=file, flush=flush)
    builtins.print = _themed_print  # type: ignore[assignment]
    install_global_console._installed = True  # type: ignore[attr-defined]


# ── Demo (run: python -m agents.ui_theme) ─────────────────────────────────────
if __name__ == "__main__":
    import time

    ui.banner("AIM v7.0", subtitle="Assistant of Integrative Medicine")

    ui.kv({
        "Provider": "DeepSeek V4 (flash + pro)",
        "Patient":  "Иванова Е.И., 67 лет",
        "Lang":     "ru",
        "Session":  "#42",
    }, title="Status")

    ui.divider("session start")

    ui.user("Подскажи дифференциалы при HGB 75, MCV 68, RDW 18.5")

    with ui.spinner("DeepSeek-v4-pro reasoning…"):
        time.sleep(0.6)

    ui.tool_call("ssa.syndromes", {"HGB": 75, "MCV": 68, "RDW": 18.5})
    ui.tool_result("matched 1 pattern: ANEMIA_MICROCYTIC_IDA (amber)")

    ui.assistant(
        "На вход подан паттерн **микроцитарной анемии**. Топ-3 дифряд:\n\n"
        "1. ЖДА (дефицит железа) — ferritin↓, TSAT↓\n"
        "2. Анемия хронических болезней — ferritin норм/↑, ESR↑\n"
        "3. Талассемия (β-trait) — RBC↑, RDW нормальный\n",
        markdown=True,
    )

    ui.process("intake.ocr",   duration=4.2, detail="3 страницы PDF → текст")
    ui.process("llm.deepseek", duration=2.1, detail="cache hit 65%")
    ui.process("ssa.match",    duration=0.0)

    ui.divider()

    ui.success("Отчёт сохранён → reports/case_42.pdf")
    ui.warning("Глюкоза 7.8 ммоль/л — выше верхнего критического (H2)")
    ui.info("Cost session: $0.014 (DeepSeek V4 Pro × 1, V4 Flash × 3)")
    ui.error("Groq API: rate-limit, fallback на DeepSeek-v4-flash")

    ui.divider("end")
