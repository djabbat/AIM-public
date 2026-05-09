"""agents/aider_tool.py — Aider wrapper with post-edit validation.

Spawns Aider as a subprocess with the AIM-standard flags, then runs lightweight
linters/tests against changed files. If validation fails, the structured result
returned upstream contains the errors so the executor can decide how to react.

Used by graph._maybe_run_aider when an executor step requires file edits, but
also callable standalone:

    from agents.aider_tool import AiderTool
    tool = AiderTool(["myfile.py"])
    print(tool.edit("Refactor to use async/await"))
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("aim.aider_tool")

AIDER_BIN = "/home/oem/.local/bin/aider"
DEFAULT_MODEL = "deepseek/deepseek-chat"

# Per-extension validation commands. Keys are file suffixes (lowercase).
# {file} is replaced with the absolute path. Commands missing on $PATH are skipped.
VALIDATION_COMMANDS: dict[str, list[str]] = {
    ".py": [
        "python3 -m py_compile {file}",
        "ruff check {file}",
    ],
    ".sh": [
        "bash -n {file}",
        "shellcheck {file}",
    ],
    ".json": [
        "python3 -c 'import json,sys; json.load(open(sys.argv[1]))' {file}",
    ],
    ".md": [],   # nothing useful to lint
}


@dataclass
class ValidationResult:
    success: bool = True
    errors: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class AiderResult:
    success: bool
    stdout: str
    validation: ValidationResult
    diff: str = ""


class AiderTool:
    def __init__(self, files: list[str], model: str = DEFAULT_MODEL,
                 timeout_s: int = 180) -> None:
        self.files = [str(Path(f).resolve()) for f in files]
        self.model = model
        self.timeout_s = timeout_s

    # ── public API ──────────────────────────────────────────────────────────

    def edit(self, instruction: str) -> AiderResult:
        if not self.files:
            return AiderResult(False, "нет файлов",
                               ValidationResult(False, ["files=[]"], "no files supplied"))
        if not Path(AIDER_BIN).exists() and not shutil.which("aider"):
            return AiderResult(False, "", ValidationResult(False,
                ["aider not installed"], "❌ aider not on PATH"))

        cmd = [
            AIDER_BIN if Path(AIDER_BIN).exists() else "aider",
            "--model", self.model,
            "--no-git",
            "--yes-always",
            "--message", instruction,
            *self.files,
        ]
        log.info(f"aider: {instruction[:80]}…")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            return AiderResult(False, "", ValidationResult(False,
                ["aider timeout"], f"⚠️  timeout after {self.timeout_s}s"))

        ok = proc.returncode == 0
        validation = self.validate() if ok else ValidationResult(
            success=False,
            errors=[proc.stderr[:600]],
            summary=f"❌ aider exit code {proc.returncode}",
        )
        return AiderResult(
            success=ok and validation.success,
            stdout=proc.stdout[-2000:],
            validation=validation,
            diff=self.diff(),
        )

    def validate(self) -> ValidationResult:
        result = ValidationResult()
        for f in self.files:
            ext = Path(f).suffix.lower()
            cmds = VALIDATION_COMMANDS.get(ext)
            if cmds is None:
                continue   # unknown ext, skip
            for tpl in cmds:
                tool = tpl.split()[0]
                if not shutil.which(tool):
                    log.debug(f"validator '{tool}' not on PATH; skipping")
                    continue
                cmd = tpl.format(file=f)
                try:
                    subprocess.run(cmd, shell=True, check=True,
                                   capture_output=True, text=True, timeout=30)
                except subprocess.CalledProcessError as e:
                    result.success = False
                    result.errors.append(f"{Path(f).name}: {tool}\n{e.stderr[:300]}")
                except subprocess.TimeoutExpired:
                    result.errors.append(f"{Path(f).name}: {tool} timeout")
                    result.success = False
        result.summary = ("✅ валидация пройдена" if result.success
                          else f"❌ ошибок валидации: {len(result.errors)}")
        return result

    def diff(self) -> str:
        """Best-effort `git diff` for the affected files. Empty if not a repo."""
        try:
            res = subprocess.run(["git", "diff", "--", *self.files],
                                 capture_output=True, text=True, timeout=10)
            return res.stdout
        except Exception:
            return ""


def _format_for_executor(result: AiderResult) -> str:
    """Render an AiderResult as a markdown block for the executor result list."""
    pieces = ["[aider]"]
    if result.success:
        pieces.append(result.validation.summary)
    else:
        pieces.append(result.validation.summary)
        for e in result.validation.errors[:5]:
            pieces.append(f"  - {e}")
    if result.stdout.strip():
        pieces.append("\n```\n" + result.stdout.strip()[-1500:] + "\n```")
    if result.diff:
        pieces.append("\n```diff\n" + result.diff[:1500] + "\n```")
    return "\n".join(pieces)
