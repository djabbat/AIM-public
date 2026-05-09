#!/usr/bin/env python3
"""AIM AI free-form REPL — Claude Code-style non-blocking terminal.

Архитектура:
  • prompt_toolkit Application с split layout:
      [output_window]   ← scrollable, append-only вывод
      [status_line]     ← spinner + tools count + queue + state
      [input_frame]     ← всегда активная многострочная панель ввода
  • Worker thread читает задачи из queue.Queue и вызывает agents.generalist.run
    с on_event callback. Events идут в очередь, основной worker-loop
    дренит их и эмитит на UI.
  • Пользователь может писать новый запрос пока AI работает — встанет
    в очередь.
  • Conversation history (user↔assistant пары) копится в _conversation
    и префиксируется в каждый task — generalist.run() не поддерживает
    передачу истории напрямую.
  • Identity-prefix защищает от галлюцинации модели "я Claude".
"""
from __future__ import annotations

import os

# Заглушаем шумные progress-bars моделей до любых импортов.
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("DISABLE_TQDM", "1")

import queue
import re
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

AIM_ROOT = Path("/home/oem/Desktop/LongevityCommon/AIM")
sys.path.insert(0, str(AIM_ROOT))


# ── stderr noise filter ─────────────────────────────────────────────────────
_NOISE_PATTERNS = (
    "Loading weights",
    "Loading checkpoint",
    "Fetching ",
    "Downloading ",
    "model.safetensors",
)


class _FilteredStderr:
    def __init__(self, real):
        self._real = real
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while True:
            idx = -1
            for sep in ("\r", "\n"):
                i = self._buf.find(sep)
                if i != -1 and (idx == -1 or i < idx):
                    idx = i
            if idx == -1:
                break
            line, self._buf = self._buf[: idx + 1], self._buf[idx + 1 :]
            if not any(p in line for p in _NOISE_PATTERNS):
                self._real.write(line)
        return len(s)

    def flush(self) -> None:
        if self._buf and not any(p in self._buf for p in _NOISE_PATTERNS):
            self._real.write(self._buf)
        self._buf = ""
        self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


sys.stderr = _FilteredStderr(sys.stderr)


# ── prompt_toolkit imports ──────────────────────────────────────────────────
from prompt_toolkit import Application  # noqa: E402
from prompt_toolkit.buffer import Buffer  # noqa: E402
from prompt_toolkit.filters import has_focus  # noqa: E402
from prompt_toolkit.history import FileHistory  # noqa: E402
from prompt_toolkit.key_binding import KeyBindings  # noqa: E402
from prompt_toolkit.layout import HSplit, Layout, Window  # noqa: E402
from prompt_toolkit.layout.controls import (  # noqa: E402
    BufferControl, FormattedTextControl,
)
from prompt_toolkit.layout.dimension import Dimension as D  # noqa: E402
from prompt_toolkit.layout.margins import ScrollbarMargin  # noqa: E402
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType  # noqa: E402
from prompt_toolkit.styles import Style  # noqa: E402
from prompt_toolkit.widgets import Frame  # noqa: E402


HIST_PATH = Path.home() / ".cache" / "aim" / "ai_repl_history"
HIST_PATH.parent.mkdir(parents=True, exist_ok=True)

DEBUG_LOG = Path.home() / ".cache" / "aim" / "repl_debug.log"
LANG_PATH = Path.home() / ".cache" / "aim" / "repl_lang"
TODOS_PATH = Path.home() / ".cache" / "aim" / "repl_todos.json"

# Языки для REPL UI: 6 UN + грузинский (по требованию пользователя).
# Default = en. Выбор сохраняется в LANG_PATH между сессиями.
REPL_LANGS = ("en", "fr", "es", "ar", "zh", "ru", "ka")
_LANG_NAMES = {
    "en": "English",   "fr": "Français",  "es": "Español",
    "ar": "العربية",   "zh": "中文",      "ru": "Русский",
    "ka": "ქართული",
}


def _load_lang() -> str:
    try:
        v = LANG_PATH.read_text(encoding="utf-8").strip()
        if v in REPL_LANGS:
            return v
    except (OSError, UnicodeDecodeError):
        pass
    return "en"


def _save_lang(code: str) -> None:
    try:
        LANG_PATH.write_text(code, encoding="utf-8")
    except OSError:
        pass


_lang = _load_lang()


def _t(key: str, **fmt) -> str:
    """Перевод через i18n с подстановкой именованных параметров."""
    from i18n import t as _i18n_t
    s = _i18n_t(key, _lang)
    if fmt:
        try:
            return s.format(**fmt)
        except (KeyError, IndexError):
            return s
    return s


def _dlog(msg: str) -> None:
    """Append-only debug log: каждый ход worker'а пишется сюда."""
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:  # noqa: BLE001
        pass


# ── Shared state ────────────────────────────────────────────────────────────
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_output_fragments: list[tuple[str, str]] = []
_output_lock = threading.Lock()

_state: dict[str, Any] = {
    "busy": False,
    "label": "",
    "t0": 0.0,
    "interrupt": False,
    "iter": 0,
    "tool_count": 0,
    "last_tool_t": 0.0,
}
_state_lock = threading.Lock()

_task_queue: "queue.Queue[str]" = queue.Queue()
_stop_event = threading.Event()
_app: Application | None = None

_scroll = {"manual": False, "offset": 0}

# TODO panel state — заполняется AI через `todo_write` tool (пишется в
# TODOS_PATH). REPL polls файл и рендерит чеклист сверху output area.
_todos: list[dict] = []
_todos_mtime: float = 0.0


def _load_todos() -> bool:
    """Read TODOS_PATH if changed since last load. Returns True when the
    in-memory list actually changed (so callers can skip redraws when no
    update happened — avoids ticker-driven flicker that wipes mouse
    selection)."""
    global _todos, _todos_mtime
    try:
        st = TODOS_PATH.stat()
    except (FileNotFoundError, PermissionError):
        if _todos:
            _todos = []
            _todos_mtime = 0.0
            return True
        return False
    if st.st_mtime <= _todos_mtime:
        return False
    try:
        import json as _j
        data = _j.loads(TODOS_PATH.read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            _todos = [
                {
                    "id": str(it.get("id", "")),
                    "content": str(it.get("content", "")),
                    "status": str(it.get("status", "pending")),
                }
                for it in items if isinstance(it, dict)
            ]
            _todos_mtime = st.st_mtime
            return True
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return False

# Conversation history (накапливаем user↔assistant в этой сессии REPL).
_conversation: list[dict] = []
_CONV_MAX_TURNS = 12
_CONV_MAX_ANSWER_CHARS = 1800

def _identity_prefix() -> str:
    """Identity-блок для LLM. Содержит требование отвечать на текущем
    языке UI пользователя — иначе модель отвечает на языке вопроса
    или дефолтном (часто English/Chinese для DeepSeek)."""
    name = _LANG_NAMES.get(_lang, "English")
    return (
        "[IDENTITY — must comply]\n"
        "You are AIM AI: assistant for Jaba Tkemaladze (Georgia Longevity "
        "Alliance), running on DeepSeek-V4 (flash for default, pro for "
        "reasoning). You are NOT Claude, NOT ChatGPT, NOT GPT-4, "
        "NOT an Anthropic model. If asked «who are you», «what model», "
        "«what context window» — answer: «AIM AI on DeepSeek-V4 (1M context). "
        "GLA assistant».\n"
        f"User UI language: {_lang} ({name}). "
        f"ALWAYS reply in {name} unless the user explicitly asks otherwise.\n"
        "[/IDENTITY]"
    )


def _build_task_with_context(task: str) -> str:
    """Префиксирует task identity-hint'ом + последними ходами разговора."""
    parts = [_identity_prefix()]
    if _conversation:
        parts.append(
            "[PREVIOUS CONVERSATION IN THIS SESSION — consider when answering]")
        for turn in _conversation[-_CONV_MAX_TURNS:]:
            ans = turn["assistant"]
            if len(ans) > _CONV_MAX_ANSWER_CHARS:
                ans = ans[:_CONV_MAX_ANSWER_CHARS] + "…"
            parts.append(f"USER: {turn['user']}")
            parts.append(f"ASSISTANT: {ans}")
        parts.append("[/PREVIOUS CONVERSATION]")
    parts.append(f"[CURRENT USER QUESTION]\n{task}")
    return "\n\n".join(parts)


def _invalidate() -> None:
    if _app is not None:
        try:
            _app.invalidate()
        except Exception:  # noqa: BLE001
            pass


def _emit_fragments(fragments: list[tuple[str, str]]) -> None:
    with _output_lock:
        _output_fragments.extend(fragments)
        if len(_output_fragments) > 8000:
            del _output_fragments[: len(_output_fragments) - 6000]
    _invalidate()


def _emit(style: str, text: str) -> None:
    _emit_fragments([(style, text)])


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except (AttributeError, OSError):
        return 100


# ── Output helpers ──────────────────────────────────────────────────────────
def emit_user(task: str) -> None:
    _emit("class:rule", "─" * min(200, max(20, _term_width() - 2)) + "\n")
    _emit("class:user", "you ▸ ")
    _emit("", task + "\n")


def emit_tool_call(name: str, args: Any) -> None:
    args_str = _format_args(args)
    _emit("class:tool", f"  ⚒ {name}")
    if args_str:
        _emit("class:dim", f" {args_str}")
    _emit("", "\n")


def emit_tool_result(ev: dict) -> None:
    ok = ev.get("ok", True)
    sym = "  ✓ " if ok else "  ✗ "
    style = "class:ok" if ok else "class:err"
    preview = ev.get("result_preview") or ev.get("preview") or ""
    # Tool result preview — всего 1 строка (120 chars max), чтобы
    # не съедало вертикальное пространство видимой области output.
    if isinstance(preview, str):
        first_line = preview.split("\n", 1)[0].strip()
        if len(first_line) > 120:
            first_line = first_line[:117] + "…"
        preview = _deactivate_urls(first_line)
    _emit(style, sym)
    if preview:
        _emit("class:dim", str(preview))
    _emit("", "\n")


def _format_answer_plain(text: str) -> str:
    """Lightweight markdown rendering без rich: абзацы через blank lines,
    wrap по ширине, заголовки `#` → `▍ Heading`, списки сохраняются.
    Возвращает один текст (даст ровно 1 fragment в FormattedText) —
    auto-scroll prompt_toolkit работает корректно."""
    if not text:
        return ""
    width = max(40, _term_width() - 4)
    out: list[str] = []
    in_code = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append("    " + line)
            continue
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            prefix = "▍ " if level == 1 else "▎ " if level == 2 else "· "
            out.append(prefix + m.group(2))
            continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$", line)
        if m:
            indent, marker, body = m.group(1), m.group(2), m.group(3)
            wrapped = textwrap.fill(
                body, width=width,
                initial_indent=f"{indent}{marker} ",
                subsequent_indent=indent + " " * (len(marker) + 1),
                break_long_words=False, break_on_hyphens=False,
            )
            out.append(wrapped)
            continue
        wrapped = textwrap.fill(line, width=width,
                                break_long_words=False, break_on_hyphens=False)
        out.append(wrapped)
    text_out = "\n".join(out)
    # Снимаем markdown-маркеры (в plain режиме без рендера они шумят):
    text_out = re.sub(r"\*\*(.+?)\*\*", r"\1", text_out)  # **bold**
    text_out = re.sub(r"__(.+?)__",     r"\1", text_out)  # __bold__
    text_out = re.sub(r"`([^`]+?)`",    r"\1", text_out)  # `code`
    return text_out


_last_final_answer: str = ""


def emit_final(answer: str) -> None:
    global _last_final_answer
    if not answer:
        _emit("class:dim", _t("repl_empty_answer") + "\n")
        return
    _last_final_answer = answer
    # Persist last final answer to disk so the user can `cat`/open it
    # without fighting full-screen alt-buffer mouse selection.
    try:
        last_path = Path.home() / ".cache" / "aim" / "last_answer.md"
        last_path.parent.mkdir(parents=True, exist_ok=True)
        last_path.write_text(answer, encoding="utf-8")
    except OSError:
        pass
    formatted = _format_answer_plain(answer)
    _emit("", "\n")
    _emit("class:answer", formatted + "\n")


def emit_footer(out: dict, elapsed: float) -> None:
    tools = ", ".join(out.get("tools_used", []) or ["—"])
    iters = out.get("iters", "?")
    _emit("class:dim",
          f"[tools: {tools}  ·  iters: {iters}  ·  {elapsed:.1f}s]\n\n")


def emit_error(msg: str) -> None:
    _emit("class:err", f"\n[error] {msg}\n\n")


def emit_system(msg: str) -> None:
    _emit("class:warn", f"  {msg}\n")


_URL_DEACTIVATE_RE = re.compile(r"\b(https?)://")


def _deactivate_urls(s: str) -> str:
    """Insert U+200B (zero-width space) between scheme and `://` so the
    terminal stops auto-detecting it as a clickable hyperlink. Without
    this, gnome-terminal hijacks mouse events on URL spans, breaking
    Ctrl+Shift+C copy of nearby text. Visual width unchanged."""
    return _URL_DEACTIVATE_RE.sub(r"\1​://", s)


def _format_args(args: Any) -> str:
    if not args:
        return ""
    if isinstance(args, str):
        s = args.strip()
    else:
        try:
            import json as _j
            s = _j.dumps(args, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            s = str(args)
    s = _deactivate_urls(s)
    return s if len(s) <= 100 else s[:97] + "…"


# ── Worker thread ───────────────────────────────────────────────────────────
def _worker_loop() -> None:
    try:
        from agents.generalist import run
    except Exception as e:  # noqa: BLE001
        emit_error(f"failed to import generalist: {e}")
        return

    while not _stop_event.is_set():
        try:
            task = _task_queue.get(timeout=0.3)
        except queue.Empty:
            continue

        with _state_lock:
            _state["busy"] = True
            _state["label"] = _t("repl_status_thinking")
            _state["t0"] = time.monotonic()
            _state["interrupt"] = False
            _state["iter"] = 0
            _state["tool_count"] = 0
            _state["last_tool_t"] = time.monotonic()
        _invalidate()

        ev_queue: "queue.Queue[dict]" = queue.Queue()

        def _on_event(ev: dict) -> None:
            ev_queue.put(ev)

        out: dict = {}
        err: str = ""
        full_task = _build_task_with_context(task)

        run_done = threading.Event()
        run_result: dict = {}
        run_error: list[str] = []

        def _run_target():
            try:
                r = run(full_task, max_iters=20, on_event=_on_event)
                run_result.update(r or {})
            except Exception as ex:  # noqa: BLE001
                run_error.append(f"{type(ex).__name__}: {ex}")
            finally:
                run_done.set()

        run_thread = threading.Thread(target=_run_target, daemon=True)
        run_thread.start()

        while not run_done.is_set() or not ev_queue.empty():
            try:
                ev = ev_queue.get(timeout=0.1)
            except queue.Empty:
                with _state_lock:
                    if _state["interrupt"]:
                        emit_system(_t("repl_interrupted"))
                        break
                _invalidate()
                continue

            t = ev.get("type")
            if t == "tool_call":
                name = ev.get("tool", "?")
                with _state_lock:
                    _state["label"] = f"{name}…"
                    _state["tool_count"] += 1
                    _state["last_tool_t"] = time.monotonic()
                emit_tool_call(name, ev.get("args"))
            elif t == "tool_result":
                emit_tool_result(ev)
            elif t == "final":
                if not out:
                    out = ev
            elif t == "error":
                err = ev.get("error", "unknown")
            _invalidate()

        run_thread.join(timeout=2.0)

        if run_error and not err:
            err = run_error[0]

        if not out and run_result:
            out = run_result

        _dlog(f"loop_end task={task[:60]!r} run_done={run_done.is_set()} "
              f"out_keys={list(out.keys()) if out else []} "
              f"answer_len={len(out.get('answer', '')) if out else 0} "
              f"err={err[:100]!r}")

        if not out and not err:
            err = _t("repl_worker_silent")

        elapsed = time.monotonic() - _state["t0"]
        try:
            if err:
                emit_error(err)
            elif out:
                answer = out.get("answer", "")
                emit_final(answer)
                emit_footer(out, elapsed)
                if answer:
                    _conversation.append({"user": task, "assistant": answer})
        except Exception as ex:  # noqa: BLE001
            _dlog(f"EMIT EXCEPTION: {type(ex).__name__}: {ex}")
            _emit("class:err",
                  f"\n[render error] {type(ex).__name__}: {ex}\n\n")
            if out and out.get("answer"):
                _emit("", out["answer"] + "\n")

        with _state_lock:
            _state["busy"] = False
            _state["label"] = ""
        _invalidate()


# ── UI: status line ─────────────────────────────────────────────────────────
_TOK_BASELINE = {"calls": 0, "cost": 0.0, "in": 0, "out": 0,
                  "captured": False}
_TOK_CACHE = {"ts": 0.0, "session_in": 0, "session_out": 0,
               "session_cost": 0.0, "daily_cost": 0.0}


def _capture_token_baseline_once() -> None:
    """Snapshot cumulative tokens AT THE TIME THE REPL STARTS so 'session
    consumption' = delta since this REPL launched. cost_monitor.stats()
    is queried once and cached."""
    if _TOK_BASELINE["captured"]:
        return
    try:
        from agents.cost_monitor import stats as _cm_stats
        s = _cm_stats()
        _TOK_BASELINE.update({
            "calls": int(s.get("total_calls", 0)),
            "cost":  float(s.get("total_cost", 0.0)),
            "in":    int(s.get("total_input_tokens", 0)),
            "out":   int(s.get("total_output_tokens", 0)),
            "captured": True,
        })
    except Exception:
        # cost_monitor unavailable — silently skip token panel
        _TOK_BASELINE["captured"] = True


def _refresh_token_cache() -> None:
    """Re-query cost_monitor at most every 2s. Called from _render_status."""
    now = time.monotonic()
    if now - _TOK_CACHE["ts"] < 2.0:
        return
    _TOK_CACHE["ts"] = now
    if not _TOK_BASELINE["captured"]:
        _capture_token_baseline_once()
    try:
        from agents.cost_monitor import stats as _cm_stats
        s = _cm_stats()
        _TOK_CACHE["session_in"]   = int(s.get("total_input_tokens", 0))  - _TOK_BASELINE["in"]
        _TOK_CACHE["session_out"]  = int(s.get("total_output_tokens", 0)) - _TOK_BASELINE["out"]
        _TOK_CACHE["session_cost"] = float(s.get("total_cost", 0.0))      - _TOK_BASELINE["cost"]
        _TOK_CACHE["daily_cost"]   = float(s.get("daily_cost", 0.0))
    except Exception:
        pass


def _format_tokens(n: int) -> str:
    """Compact: 1234 → '1.2K', 1234567 → '1.2M'."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n/1000:.1f}K"
    return f"{n/1_000_000:.2f}M"


def _token_status_fragment() -> tuple[str, str]:
    """Return (style, text) tuple for status-bar token panel, or empty
    text if not available."""
    _refresh_token_cache()
    sin = _TOK_CACHE["session_in"]
    sout = _TOK_CACHE["session_out"]
    scost = _TOK_CACHE["session_cost"]
    dcost = _TOK_CACHE["daily_cost"]
    if sin == 0 and sout == 0:
        return ("class:dim", "")
    return ("class:dim",
            f"  · tok: {_format_tokens(sin)}↑ {_format_tokens(sout)}↓ "
            f"${scost:.3f} / day ${dcost:.2f}")


def _render_status():
    with _state_lock:
        busy = _state["busy"]
        label = _state["label"]
        t0 = _state["t0"]
        tool_count = _state["tool_count"]
        last_tool_t = _state["last_tool_t"]
    qsize = _task_queue.qsize()
    if busy:
        now = time.monotonic()
        elapsed = now - t0
        idle_for = now - last_tool_t
        frame = SPINNER_FRAMES[int(elapsed * 12) % len(SPINNER_FRAMES)]
        parts = [
            ("class:spinner", f" {frame} "),
            ("class:label", label),
            ("class:dim", f"  {elapsed:5.1f}s"),
            ("class:dim", f"  · tools: {tool_count}"),
        ]
        if idle_for > 60 and tool_count > 0:
            warn = _t("repl_status_warn_hung")
            warn_q = _t("repl_status_warn_hung_q")
            parts.append(("class:warn",
                          f"  · ⚠ {warn} {idle_for:.0f}s {warn_q}"))
        elif elapsed > 120:
            parts.append(("class:warn",
                          f"  · ⚠ {_t('repl_status_warn_long')}"))
        if qsize:
            parts.append(("class:queue", f"  · queue: {qsize}"))
        tok_frag = _token_status_fragment()
        if tok_frag[1]:
            parts.append(tok_frag)
        parts.append(("class:dim", f"  · {_t('repl_status_interrupt_hint')}"))
        return parts
    base = [
        ("class:idle", " ● "),
        ("class:label", _t("repl_status_idle")),
        ("class:dim", f"  · [{_lang}] AIM AI · DeepSeek-V4"),
    ]
    if qsize:
        base.append(("class:queue", f"  · queue: {qsize}"))
    tok_frag = _token_status_fragment()
    if tok_frag[1]:
        base.append(tok_frag)
    return base


# ── UI: output window ───────────────────────────────────────────────────────
def _output_text():
    with _output_lock:
        return list(_output_fragments)


# ── TODO panel ──────────────────────────────────────────────────────────────
def _render_todos():
    """Возвращает FormattedText fragments для top panel чеклиста.
    Рисует только если есть items. Маркеры: ▢ pending · ▣ in_progress · ☑ done."""
    _load_todos()
    if not _todos:
        return []
    parts: list[tuple[str, str]] = []
    done = sum(1 for t in _todos if t["status"] == "completed")
    total = len(_todos)
    parts.append(("class:todo-header",
                  f" ▷ Tasks ({done}/{total})\n"))
    for t in _todos:
        s = t["status"]
        if s == "completed":
            parts.append(("class:todo-done", "  ☑ "))
            parts.append(("class:todo-done-text", t["content"]))
        elif s == "in_progress":
            parts.append(("class:todo-active", "  ▣ "))
            parts.append(("class:todo-active-text", t["content"]))
        else:
            parts.append(("class:todo-pending", "  ▢ "))
            parts.append(("class:todo-pending-text", t["content"]))
        parts.append(("", "\n"))
    parts.append(("class:rule", "─" * min(200, max(20, _term_width() - 2)) + "\n"))
    return parts


def _todo_height():
    """Dynamic height: 0 когда todos пусто (panel невидим), иначе по числу
    items с потолком в 12. ConditionalContainer ломал layout — Window с
    callable height стабильнее."""
    if not _todos:
        return D.exact(0)
    # 1 (header) + len(_todos) + 1 (rule) ≤ 12
    n = min(12, 2 + len(_todos))
    return D(min=n, max=n)


todo_window = Window(
    content=FormattedTextControl(text=_render_todos, focusable=False),
    wrap_lines=True,
    always_hide_cursor=True,
    height=_todo_height,
)


def _get_vscroll(w):
    """Manual offset OR very large number → prompt_toolkit clamp до
    реального максимума с учётом wrapped lines. Надёжнее чем считать
    bottom через line_count (не учитывает wrap)."""
    if _scroll["manual"]:
        return _scroll["offset"]
    return 10**9


def _scroll_up(step: int = 3) -> None:
    """Mouse-wheel-up handler: scroll the output window up by `step` lines.
    Mirrors PgUp behaviour but in smaller steps for ergonomic wheel use."""
    info = output_window.render_info
    if not info:
        return
    bottom = max(0, info.content_height - info.window_height)
    cur = _scroll["offset"] if _scroll["manual"] else bottom
    _scroll["manual"] = True
    _scroll["offset"] = max(0, cur - step)


def _scroll_down(step: int = 3) -> None:
    info = output_window.render_info
    if not info:
        return
    bottom = max(0, info.content_height - info.window_height)
    cur = _scroll["offset"] if _scroll["manual"] else bottom
    new = cur + step
    if new >= bottom:
        _scroll["manual"] = False
    else:
        _scroll["offset"] = new


class _ScrollableTextControl(FormattedTextControl):
    """FormattedTextControl that intercepts wheel events for output scroll.
    `mouse_handler` is a method, not a constructor kwarg, so subclassing
    is the supported way to override it."""

    def mouse_handler(self, mouse_event):
        et = getattr(mouse_event, "event_type", None)
        if et == MouseEventType.SCROLL_UP:
            _scroll_up()
            return None
        if et == MouseEventType.SCROLL_DOWN:
            _scroll_down()
            return None
        return NotImplemented


output_window = Window(
    content=_ScrollableTextControl(text=_output_text, focusable=False,
                                   show_cursor=False),
    wrap_lines=True,
    always_hide_cursor=True,
    right_margins=[ScrollbarMargin(display_arrows=True)],
    get_vertical_scroll=_get_vscroll,
)

status_window = Window(
    content=FormattedTextControl(text=_render_status, focusable=False),
    height=1,
    style="class:status",
)


# ── UI: input area ──────────────────────────────────────────────────────────
input_buffer = Buffer(
    multiline=True,
    history=FileHistory(str(HIST_PATH)),
    enable_history_search=True,
)

input_window = Window(
    content=BufferControl(buffer=input_buffer, focusable=True),
    wrap_lines=True,
    height=D(min=1, max=10, preferred=2),
)

def _input_frame_title():
    return _t("repl_input_title")


input_frame = Frame(
    body=input_window,
    title=_input_frame_title,
    style="class:input-frame",
)


# ── Slash commands ──────────────────────────────────────────────────────────
def _handle_repl_command(text: str) -> bool:
    global _lang
    raw = text.strip()
    cmd = raw.lower()
    head = cmd.split(maxsplit=1)[0] if cmd else cmd

    if head in ("/clear", "/reset"):
        _conversation.clear()
        with _output_lock:
            _output_fragments.clear()
        _emit("class:warn", _t("repl_cmd_clear_done") + "\n\n")
        return True

    if head in ("/history", "/ctx"):
        _emit("class:dim",
              "\n" + _t("repl_cmd_history_header", n=len(_conversation)) + "\n")
        for i, turn in enumerate(_conversation[-_CONV_MAX_TURNS:], 1):
            u = turn["user"][:80]
            a = turn["assistant"][:80].replace("\n", " ")
            _emit("class:dim", f"  {i:2d}. user: {u}\n")
            _emit("class:dim", f"      assistant: {a}…\n")
        _emit("", "\n")
        return True

    if head in ("/help", "/?"):
        _emit("class:dim", "\n" + _t("repl_cmd_help_text") + "\n\n")
        _emit("class:dim",
              "  /save [path]  — write last answer to file\n"
              "                  (default: ~/.cache/aim/last_answer.md;\n"
              "                   workaround for mouse-copy in full-screen REPL)\n"
              "  /cost         — show session token/cost stats + today/month totals\n"
              "  /tokens       — alias for /cost\n\n")
        return True

    if head in ("/cost", "/tokens"):
        try:
            from agents.cost_monitor import stats as _cm_stats
            s = _cm_stats()
        except Exception as e:
            _emit("class:err", f"\n  ✗ cost_monitor unavailable: {e}\n\n")
            return True
        _refresh_token_cache()
        sin = _TOK_CACHE["session_in"]
        sout = _TOK_CACHE["session_out"]
        scost = _TOK_CACHE["session_cost"]
        _emit("class:warn", "\n  Token & cost stats\n")
        _emit("class:dim",
              f"    Session (since AIM start):\n"
              f"      input:  {sin:>10,} tokens\n"
              f"      output: {sout:>10,} tokens\n"
              f"      cost:   ${scost:.4f}\n"
              f"    Today:    ${s.get('daily_cost', 0):.3f} "
              f"/ ${s.get('daily_limit', 0):.2f} daily limit\n"
              f"    Month:    ${s.get('monthly_cost', 0):.3f} "
              f"/ ${s.get('monthly_limit', 0):.2f} monthly limit\n"
              f"    Total calls (all time): {s.get('total_calls', 0):,}\n"
              f"    Total cost  (all time): ${s.get('total_cost', 0):.2f}\n")
        by_model = s.get('cost_by_model_7d', {})
        if by_model:
            _emit("class:dim", "    Last 7 days by model:\n")
            for m, c in sorted(by_model.items(), key=lambda x: -x[1])[:6]:
                _emit("class:dim", f"      {m:<28} ${c:.4f}\n")
        _emit("", "\n")
        return True

    if head in ("/save", "/copy"):
        if not _last_final_answer:
            _emit("class:warn", "\n  no answer yet — ask AIM something first\n\n")
            return True
        parts = raw.split(maxsplit=1)
        if len(parts) == 2:
            target = Path(parts[1].strip()).expanduser()
        else:
            target = Path.home() / ".cache" / "aim" / "last_answer.md"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_last_final_answer, encoding="utf-8")
            _emit("class:ok",
                  f"\n  ✓ saved {len(_last_final_answer)} chars → {target}\n\n")
        except OSError as e:
            _emit("class:err", f"\n  ✗ save failed: {e}\n\n")
        return True

    if head in ("/language", "/lang"):
        # `/language` без аргумента — показать селектор
        # `/language en` (или fr/es/ar/zh/ru/ka) — переключить
        parts = raw.split(maxsplit=1)
        if len(parts) == 1:
            _emit("class:warn", "\n" + _t("repl_lang_select_header") + "\n")
            for code in REPL_LANGS:
                marker = " ← current" if code == _lang else ""
                _emit("class:dim",
                      f"  /language {code}  ·  {_LANG_NAMES[code]}{marker}\n")
            _emit("class:dim", "\n" + _t("repl_lang_select_hint") + "\n\n")
            return True
        new_lang = parts[1].strip().lower()
        if new_lang not in REPL_LANGS:
            _emit("class:err",
                  "\n" + _t("repl_lang_unknown", code=new_lang) + "\n\n")
            return True
        _lang = new_lang
        _save_lang(new_lang)
        _emit("class:warn",
              "\n" + _t("repl_lang_set_to",
                        name=_LANG_NAMES[new_lang], code=new_lang) + "\n")
        # Перерисовываем баннер на новом языке (visual feedback)
        _emit_banner()
        return True

    return False


def _emit_banner() -> None:
    width = min(200, max(20, _term_width() - 2))
    _emit("class:rule", "═" * width + "\n")
    _emit("class:user", " " + _t("repl_banner_title") + "\n")
    _emit("class:dim", " " + _t("repl_banner_queue_hint") + "\n")
    _emit("class:dim", " " + _t("repl_banner_slash_hint") + "\n")
    _emit("class:dim", " " + _t("repl_banner_select_hint") + "\n")
    _emit("class:rule", "═" * width + "\n\n")


# ── Keybindings ─────────────────────────────────────────────────────────────
kb = KeyBindings()


@kb.add("enter", filter=has_focus(input_buffer))
def _enter(event):
    text = input_buffer.text.strip()
    if not text:
        return
    try:
        input_buffer.history.append_string(text)
    except Exception:  # noqa: BLE001
        pass
    input_buffer.reset()

    if _handle_repl_command(text):
        _invalidate()
        return

    # Авто-очистка видимой области перед каждым новым запросом —
    # старый ответ пропадает, контекст разговора (_conversation) сохраняется.
    with _output_lock:
        _output_fragments.clear()

    # Сбросить manual scroll — новый запрос должен авто-следовать за низом.
    _scroll["manual"] = False
    emit_user(text)
    _task_queue.put(text)
    _invalidate()


@kb.add("escape", "enter", filter=has_focus(input_buffer))
def _alt_enter(event):
    input_buffer.insert_text("\n")


@kb.add("c-j", filter=has_focus(input_buffer))
def _ctrl_j(event):
    input_buffer.insert_text("\n")


@kb.add("c-c")
def _ctrl_c(event):
    with _state_lock:
        if _state["busy"]:
            _state["interrupt"] = True
            emit_system(_t("repl_interrupt_requested"))
            return
    input_buffer.reset()


@kb.add("c-d", filter=has_focus(input_buffer))
def _ctrl_d(event):
    if not input_buffer.text:
        event.app.exit()


@kb.add("pageup")
def _pgup(event):
    info = output_window.render_info
    if not info:
        return
    bottom = max(0, info.content_height - info.window_height)
    cur = _scroll["offset"] if _scroll["manual"] else bottom
    step = max(1, info.window_height // 2)
    _scroll["manual"] = True
    _scroll["offset"] = max(0, cur - step)


@kb.add("pagedown")
def _pgdown(event):
    info = output_window.render_info
    if not info:
        return
    bottom = max(0, info.content_height - info.window_height)
    cur = _scroll["offset"] if _scroll["manual"] else bottom
    step = max(1, info.window_height // 2)
    new = cur + step
    if new >= bottom:
        _scroll["manual"] = False
    else:
        _scroll["offset"] = new


@kb.add("end")
def _end(event):
    _scroll["manual"] = False


@kb.add("home")
def _home(event):
    _scroll["manual"] = True
    _scroll["offset"] = 0


# ── Style — Claude Code-style палитра с золотым акцентом ───────────────────
style = Style.from_dict({
    "rule":         "fg:#5f5f5f",
    "user":         "fg:#d7a857 bold",
    "tool":         "fg:#ffaf00 bold",
    "ok":           "fg:#87af87",
    "err":          "fg:#d7875f bold",
    "warn":         "fg:#d7a857",
    "dim":          "fg:#6c6c6c",
    "spinner":      "fg:#ffaf00 bold",
    "idle":         "fg:#87af87",
    "label":        "fg:#d0d0d0",
    "queue":        "fg:#d7a857 bold",
    "status":       "fg:#a8a8a8 bg:#1a1a1a",
    "input-frame":  "fg:#d7a857",
    "frame.border": "fg:#d7a857",
    "frame.label":  "fg:#d7a857",
    "answer":       "fg:#dcdccc",
    # TODO panel
    "todo-header":          "fg:#d7a857 bold",
    "todo-pending":         "fg:#6c6c6c",
    "todo-pending-text":    "fg:#a8a8a8",
    "todo-active":          "fg:#ffaf00 bold",
    "todo-active-text":     "fg:#dcdccc bold",
    "todo-done":            "fg:#87af87",
    "todo-done-text":       "fg:#6c6c6c",  # done = dim (как у Claude Code)
})


# ── Layout & app ────────────────────────────────────────────────────────────
root_container = HSplit([
    todo_window,        # сверху — чеклист (виден только если AI создал todos)
    output_window,
    status_window,
    input_frame,
])

layout = Layout(container=root_container, focused_element=input_window)


def main() -> int:
    global _app

    _emit_banner()

    worker = threading.Thread(target=_worker_loop, daemon=True)
    worker.start()

    def _tick():
        # When BUSY: invalidate ~12Hz so streaming output renders smoothly.
        # When IDLE: only invalidate if todos file changed; otherwise sit
        # quiet so prompt_toolkit doesn't redraw and clobber the user's
        # mouse selection / copy buffer (gnome-terminal alt-screen issue).
        while not _stop_event.is_set():
            with _state_lock:
                busy = _state["busy"]
            if busy:
                try:
                    _load_todos()
                except Exception:  # noqa: BLE001
                    pass
                _invalidate()
                time.sleep(0.08)
            else:
                changed = False
                try:
                    changed = _load_todos()
                except Exception:  # noqa: BLE001
                    pass
                if changed:
                    _invalidate()
                # idle = poll the todos file every 1s; redraw ONLY on change
                time.sleep(1.0)
    ticker = threading.Thread(target=_tick, daemon=True)
    ticker.start()

    _app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=True,
        # mouse_support=True lets prompt_toolkit capture mouse events so we
        # can route the scroll wheel to output-window scroll (instead of
        # letting the terminal pass it to the input buffer's history nav).
        # See _output_mouse_handler.
        mouse_support=True,
    )

    try:
        _app.run()
    finally:
        _stop_event.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
