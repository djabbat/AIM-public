"""agents/memory_tui.py — terminal UI for AIM memory (curses-based, zero deps).

Pure-stdlib curses TUI: no `textual`, no `rich`, no `urwid`. Works in any
ANSI terminal. Three panes:

    [search]  top input box
    [list]    table of hits (cursor: ↑/↓, Enter = open, d = delete,
              e = edit (uses $EDITOR), p = priority cycle, / = focus search)
    [view]    full text of selected memory

Keybindings:
    /            focus search box
    Enter        run search   (in search box) | open in editor (in list)
    ↑ / ↓        move cursor
    PgUp / PgDn  page
    e            edit selected memory in $EDITOR
    d            delete selected (with confirm)
    p            cycle priority CRITICAL→HIGH→NORMAL→LOW→EPHEMERAL
    g            toggle GraphRAG mode (flat ↔ graph + hops)
    r            reload search
    q  /  Esc    quit

CLI:
    aim-memory-tui
    python -m agents.memory_tui
"""

from __future__ import annotations

import curses
import os
import re
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional


_PRIORITY_CYCLE = ("CRITICAL", "HIGH", "NORMAL", "LOW", "EPHEMERAL")


def _retrieve(query: str, mode: str, k: int = 30) -> list[dict]:
    if not query.strip():
        return []
    try:
        if mode == "graph":
            from agents.graphrag import query as gq
            return gq(query, k=k, hops=1) or []
        from agents.memory_index import retrieve
        return retrieve(query, k=k) or []
    except Exception as e:
        return [{"file": "(error)", "text": str(e)[:200], "_distance": 1.0}]


def _locate_memory_file(file_name: str) -> Optional[Path]:
    """Best-effort find the file on disk (mirrors memory_priority._locate)."""
    base = Path("~/.claude/projects/-home-oem/memory").expanduser()
    if not base.exists():
        return None
    for p in base.rglob(file_name):
        return p
    return None


def _read_frontmatter(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _set_priority(path: Path, new_priority: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", text, re.DOTALL)
    if not m:
        return False
    head, fm, tail_marker, body = m.groups()
    fm_lines = [l for l in fm.splitlines() if not l.lower().startswith("priority")]
    fm_lines.append(f"priority: {new_priority}")
    fm_lines.append(f"priority_value: {{'CRITICAL':100,'HIGH':70,'NORMAL':40,'LOW':10,'EPHEMERAL':1}}.get('{new_priority}',40)")
    new_fm = "\n".join(fm_lines)
    path.write_text(head + new_fm + tail_marker + body, encoding="utf-8")
    return True


# ── curses app ─────────────────────────────────────────────────────────────


def _truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def run(stdscr) -> None:
    curses.curs_set(1)
    stdscr.clear()
    curses.use_default_colors()
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN,    -1)   # header
        curses.init_pair(2, curses.COLOR_GREEN,   -1)   # selected
        curses.init_pair(3, curses.COLOR_YELLOW,  -1)   # priority
        curses.init_pair(4, curses.COLOR_MAGENTA, -1)   # file
        curses.init_pair(5, curses.COLOR_RED,     -1)   # error/critical

    query  = ""
    mode   = "flat"      # 'flat' | 'graph'
    hits:  list[dict] = []
    cursor = 0
    pane   = "search"    # 'search' | 'list'
    msg    = "/ search · Enter open · e edit · d delete · p priority · g mode · q quit"

    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()

        # header
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(0, 0, _truncate(f"AIM · Memory TUI · mode={mode}  ({pane})", w - 1))
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # search box
        stdscr.addstr(2, 0, "search: ")
        if pane == "search":
            stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(2, 8, _truncate(query, w - 9))
        if pane == "search":
            stdscr.attroff(curses.A_REVERSE)

        # list pane (top half)
        list_top = 4
        list_bot = h // 2 - 1
        list_h   = list_bot - list_top
        if hits:
            view_start = max(0, cursor - (list_h - 1))
            for i in range(list_h):
                idx = view_start + i
                if idx >= len(hits):
                    break
                h_ = hits[idx]
                file_str = _truncate(h_.get("file", "?"), 28)
                dist     = h_.get("_distance", 0.0)
                preview  = _truncate(h_.get("text", "").strip(), w - 40)
                line     = f" [{dist:.3f}]  {file_str:<28}  {preview}"
                if idx == cursor and pane == "list":
                    stdscr.attron(curses.color_pair(2) | curses.A_REVERSE)
                    stdscr.addstr(list_top + i, 0, _truncate(line, w - 1))
                    stdscr.attroff(curses.color_pair(2) | curses.A_REVERSE)
                else:
                    stdscr.attron(curses.color_pair(4))
                    stdscr.addstr(list_top + i, 0, _truncate(line, w - 1))
                    stdscr.attroff(curses.color_pair(4))
        else:
            stdscr.addstr(list_top, 2, "(no hits — type query and press Enter)")

        # divider
        stdscr.hline(list_bot, 0, "─", w)

        # detail pane (bottom half)
        detail_top = list_bot + 1
        if hits:
            sel = hits[cursor] if cursor < len(hits) else hits[0]
            path = _locate_memory_file(sel.get("file", ""))
            fm   = _read_frontmatter(path) if path else {}
            stdscr.attron(curses.color_pair(3))
            stdscr.addstr(detail_top, 0, _truncate(
                f"file: {sel.get('file','?')}   priority: {fm.get('priority','NORMAL')}   "
                f"category: {fm.get('category','?')}   created: {fm.get('created','?')}",
                w - 1))
            stdscr.attroff(curses.color_pair(3))

            text_lines = textwrap.wrap(sel.get("text", ""), w - 2)
            for i, line in enumerate(text_lines[: h - detail_top - 3]):
                stdscr.addstr(detail_top + 2 + i, 0, line)

        # status
        stdscr.attron(curses.color_pair(1))
        stdscr.addstr(h - 1, 0, _truncate(msg, w - 1))
        stdscr.attroff(curses.color_pair(1))

        # cursor
        if pane == "search":
            stdscr.move(2, 8 + len(query))
        else:
            stdscr.move(0, 0)
        stdscr.refresh()

        ch = stdscr.getch()

        if ch in (ord("q"), 27):    # q / Esc
            break

        if pane == "search":
            if ch in (10, 13):     # Enter
                hits = _retrieve(query, mode)
                cursor = 0
                pane = "list"
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
            elif ch == 9:           # Tab
                pane = "list"
            elif 32 <= ch < 256:
                query += chr(ch)
            continue

        # pane == 'list'
        if ch == ord("/"):
            pane = "search"
        elif ch == 9:
            pane = "search"
        elif ch == curses.KEY_DOWN and hits:
            cursor = min(len(hits) - 1, cursor + 1)
        elif ch == curses.KEY_UP and hits:
            cursor = max(0, cursor - 1)
        elif ch == curses.KEY_NPAGE and hits:
            cursor = min(len(hits) - 1, cursor + 10)
        elif ch == curses.KEY_PPAGE and hits:
            cursor = max(0, cursor - 10)
        elif ch == ord("g"):
            mode = "graph" if mode == "flat" else "flat"
            hits = _retrieve(query, mode)
            cursor = 0
        elif ch == ord("r"):
            hits = _retrieve(query, mode)
            cursor = max(0, min(cursor, len(hits) - 1))
        elif ch == ord("e") and hits:
            sel = hits[cursor]
            path = _locate_memory_file(sel.get("file", ""))
            if path:
                curses.endwin()
                editor = os.environ.get("EDITOR", "nano")
                subprocess.run([editor, str(path)])
                stdscr.refresh()
                hits = _retrieve(query, mode)
        elif ch == ord("d") and hits:
            sel = hits[cursor]
            path = _locate_memory_file(sel.get("file", ""))
            if path:
                msg = f"delete {path.name}? (y/N)"
                stdscr.addstr(h - 1, 0, " " * (w - 1))
                stdscr.addstr(h - 1, 0, msg)
                stdscr.refresh()
                if stdscr.getch() in (ord("y"), ord("Y")):
                    path.unlink()
                    hits = _retrieve(query, mode)
                    cursor = max(0, min(cursor, len(hits) - 1))
                    msg = f"deleted {path.name}"
                else:
                    msg = "cancelled"
        elif ch == ord("p") and hits:
            sel = hits[cursor]
            path = _locate_memory_file(sel.get("file", ""))
            if path:
                fm = _read_frontmatter(path)
                cur = (fm.get("priority") or "NORMAL").upper()
                idx = _PRIORITY_CYCLE.index(cur) if cur in _PRIORITY_CYCLE else 2
                new = _PRIORITY_CYCLE[(idx + 1) % len(_PRIORITY_CYCLE)]
                if _set_priority(path, new):
                    msg = f"priority {cur} → {new}"


def main() -> int:
    curses.wrapper(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
