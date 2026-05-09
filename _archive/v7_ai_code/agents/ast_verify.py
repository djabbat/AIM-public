"""agents/ast_verify.py — AST-based fact verification for AIM outputs.

Three classes of claim that regex auto-verify (orchestrator._ze_verify_output)
cannot catch on its own:

  1. SYMBOL-AT-LINE   "score_decision @ kernel.py:294" — line exists, but
                       what is actually defined there?
  2. NEGATIVE-CALL    "evaluate_l_consent has 0 external callers" — easy
                       to assert, easy to be wrong; AST gives the real list.
  3. NUMERICAL        "32 @register_tool" — count something, compare.

This module exposes pure functions used by:
  * orchestrator._ze_verify_output (auto, in-pipeline)
  * generalist tool `ze_verify_symbol`  (explicit, agent-callable)

Pure stdlib (`ast`, `pathlib`, `re`). No tree-sitter, no libcst — those add
complexity and we don't need cross-language right now.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


# ── Symbol-at-line ───────────────────────────────────────────────────────────

@dataclass
class SymbolInfo:
    name: str
    kind: str          # "def" | "async_def" | "class" | "const" | "import"
    lineno: int        # 1-based start line
    end_lineno: int    # 1-based end line (Python 3.8+ ast)


def _kind_of(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.FunctionDef):     return "def"
    if isinstance(node, ast.AsyncFunctionDef): return "async_def"
    if isinstance(node, ast.ClassDef):        return "class"
    if isinstance(node, ast.Assign):          return "const"
    if isinstance(node, (ast.Import, ast.ImportFrom)): return "import"
    return None


def def_at(file: Path | str, line: int) -> Optional[SymbolInfo]:
    """Return the top-level symbol whose body covers `line` in `file`.

    Walks only module-level statements (no nested funcs) — that matches
    what people actually claim about ("X at file:N" almost always refers
    to a top-level def/class/const).
    """
    path = Path(file)
    if not path.is_file():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"),
                         filename=str(path))
    except SyntaxError:
        return None
    for node in tree.body:
        kind = _kind_of(node)
        if kind is None:
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        if start is None or end is None:
            continue
        if start <= line <= end:
            if kind == "const":
                # Use first target name only.
                tgt = node.targets[0] if node.targets else None
                name = getattr(tgt, "id", None) if isinstance(tgt, ast.Name) else None
                if not name:
                    continue
            elif kind == "import":
                names = ", ".join(a.asname or a.name for a in node.names)
                name = names or "import"
            else:
                name = node.name
            return SymbolInfo(name=name, kind=kind,
                              lineno=start, end_lineno=end)
    return None


# ── Caller graph ─────────────────────────────────────────────────────────────

@dataclass
class Caller:
    file: str
    lineno: int


def find_callers(name: str, search_root: Path | str,
                 *, exclude_dirs: Iterable[str] = ("_archive", ".bak",
                                                    "__pycache__", "venv",
                                                    "site-packages")) -> list[Caller]:
    """Find every `Call(...)` expression whose callee resolves to `name`.

    Excludes:
      * import statements (matched by name in `ast.ImportFrom`/`ast.Import`)
      * comments / strings (we walk AST, so these are inert)
      * the file where `name` itself is defined (def in same module
        counts as a self-caller only if invoked, which is captured)

    Matches both `name(...)` and `obj.name(...)` (attribute access).
    """
    root = Path(search_root)
    bad = tuple(exclude_dirs)
    out: list[Caller] = []
    for py in root.rglob("*.py"):
        if any(b in str(py) for b in bad):
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            called = (
                f.id if isinstance(f, ast.Name)
                else f.attr if isinstance(f, ast.Attribute)
                else None
            )
            if called == name:
                out.append(Caller(file=str(py),
                                  lineno=getattr(node, "lineno", 0)))
    return out


# ── Constant extraction ──────────────────────────────────────────────────────

def extract_constant(file: Path | str, name: str) -> Optional[ast.AST]:
    """Return the AST value-node of a top-level `name = <expr>` assignment."""
    path = Path(file)
    if not path.is_file():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"),
                         filename=str(path))
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == name:
                return node.value
    return None


def constant_set_members(file: Path | str, name: str) -> Optional[list[str]]:
    """If `name` is a top-level assignment to a Set/Tuple/List literal of
    plain string constants, return the list of strings. Else None.
    """
    val = extract_constant(file, name)
    if val is None:
        return None
    if isinstance(val, (ast.Set, ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in val.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            else:
                return None
        return out
    return None


# ── Output-text scanner: extracts AST-checkable claims ───────────────────────

# 1) "<symbol> @ <path>:<N>"     →  symbol-at-line
# 2) "<path>:<N> def <symbol>"   →  symbol-at-line  (alt order)
_SYMBOL_AT_LINE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*@\s*([\w./\-]+\.py):(\d{1,7})\b"
)
_DEF_AT_LINE = re.compile(
    r"\b([\w./\-]+\.py):(\d{1,7})\s+(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]{2,})"
)

# 3) "0 (external|extern|внеш) ... callers ... <symbol>"   negative call
#    or  "<symbol> ... no (external|extern|внеш) callers"
#    or  "<symbol>: нет внешних вызовов"
_NEGATIVE_CALL_RU = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]{3,}).{0,80}?(?:нет|0|без)\s+(?:внеш\w*\s+)?(?:вызов\w*|call\w*)",
    re.IGNORECASE,
)
_NEGATIVE_CALL_EN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]{3,}).{0,80}?(?:no|zero|0)\s+(?:external\s+)?caller",
    re.IGNORECASE,
)


@dataclass
class AstClaim:
    kind: str               # "symbol_at_line" | "negative_call"
    symbol: str
    file: Optional[str] = None
    line: Optional[int] = None
    raw: str = ""


def extract_claims(text: str) -> list[AstClaim]:
    """Pull out AST-checkable claims from a piece of free-form output."""
    claims: list[AstClaim] = []
    seen: set[tuple] = set()

    def _add(c: AstClaim, key):
        if key in seen:
            return
        seen.add(key)
        claims.append(c)

    for m in _SYMBOL_AT_LINE.finditer(text):
        sym, path, ln = m.group(1), m.group(2), int(m.group(3))
        _add(AstClaim("symbol_at_line", sym, path, ln, m.group(0)),
             ("sl", sym, path, ln))
    for m in _DEF_AT_LINE.finditer(text):
        path, ln, sym = m.group(1), int(m.group(2)), m.group(3)
        _add(AstClaim("symbol_at_line", sym, path, ln, m.group(0)),
             ("sl", sym, path, ln))
    for rgx in (_NEGATIVE_CALL_RU, _NEGATIVE_CALL_EN):
        for m in rgx.finditer(text):
            sym = m.group(1)
            # Skip very common false positives
            if sym.lower() in {"нет", "no", "the", "and", "или"}:
                continue
            _add(AstClaim("negative_call", sym, raw=m.group(0)),
                 ("nc", sym))
    return claims


# ── Verify driver ────────────────────────────────────────────────────────────

@dataclass
class AstReport:
    total: int = 0
    ok: int = 0
    bad: list[str] = field(default_factory=list)


def verify_claims(text: str, *, search_root: Path | str,
                  base_dirs: Optional[list[Path]] = None,
                  subdirs: Iterable[str] = ("agents", "tools", "tests",
                                             "scripts", "web", "cli")) -> AstReport:
    """For each AST-checkable claim in `text`, verify against the file system.
    Returns counts + a list of human-readable failure strings.
    """
    rep = AstReport()
    claims = extract_claims(text)
    if not claims:
        return rep
    root = Path(search_root)
    if base_dirs is None:
        base_dirs = [root, root.parent]

    def _resolve(p: str) -> Optional[Path]:
        raw = Path(p).expanduser()
        if raw.is_absolute():
            return raw if raw.is_file() else None
        for b in base_dirs:
            cand = b / raw
            if cand.is_file():
                return cand
        if raw.parent == Path(".") or str(raw.parent) == "":
            for b in base_dirs:
                for sub in subdirs:
                    cand = b / sub / raw.name
                    if cand.is_file():
                        return cand
        return None

    for c in claims:
        rep.total += 1
        if c.kind == "symbol_at_line":
            f = _resolve(c.file or "")
            if f is None:
                rep.bad.append(f"{c.raw}: file not found")
                continue
            sym = def_at(f, c.line or 0)
            if sym is None:
                rep.bad.append(f"{c.raw}: no symbol at line {c.line}")
                continue
            if sym.name != c.symbol:
                rep.bad.append(
                    f"{c.raw}: line {c.line} actually defines "
                    f"{sym.kind} {sym.name!r}, not {c.symbol!r}")
                continue
            rep.ok += 1
        elif c.kind == "negative_call":
            callers = find_callers(c.symbol, root)
            if callers:
                where = ", ".join(f"{Path(x.file).name}:{x.lineno}"
                                  for x in callers[:5])
                rep.bad.append(
                    f"claimed '{c.symbol}' has 0 callers but found "
                    f"{len(callers)} ({where})")
                continue
            rep.ok += 1
    return rep
