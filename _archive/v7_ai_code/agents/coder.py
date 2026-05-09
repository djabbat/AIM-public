"""agents/coder.py — code-edit agent with iterate-until-tests-pass loop.

Wraps `agents.aider_tool` and adds a closed-loop runner: edit → run tests →
if failures, feed errors back to Aider with a refinement instruction, retry.
Stops at success or `max_iters` (default 3).

Public API:
    CoderAgent(files, model=None)
        .edit(instruction)            → str   # one-shot like aider_tool
        .edit_and_test(instruction,
                        test_cmd,
                        max_iters=3)  → dict  # {ok, iters, final_output, last_test}

The generalist exposes this via `delegate_coder`. L_CONSENT applies for any
write that touches tracked files outside Patients/.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from agents.aider_tool import AiderTool

log = logging.getLogger("aim.coder")


@dataclass
class CoderResult:
    ok:           bool
    iters:        int
    final_output: str
    last_test:    str
    history:      list[dict] = field(default_factory=list)


class CoderAgent:
    """One-shot edits or edit-then-test loop."""

    def __init__(self, files: Iterable[str | Path], model: Optional[str] = None):
        self.files = [str(Path(f).expanduser()) for f in files]
        self.tool = AiderTool(self.files, model=model) if model \
                    else AiderTool(self.files)

    def edit(self, instruction: str) -> str:
        """One-shot Aider edit (no test loop). Returns Aider's stdout/stderr."""
        return self.tool.edit(instruction)

    def edit_and_test(self, instruction: str, test_cmd: str,
                      *, max_iters: int = 3, cwd: Optional[str] = None) -> CoderResult:
        """Edit, then run `test_cmd`. If it fails, hand the failure back to
        Aider with a fix-the-tests instruction. Repeat up to `max_iters`."""
        history: list[dict] = []
        last_edit = self.tool.edit(instruction)
        history.append({"phase": "edit#1", "out": last_edit[-1500:]})

        for i in range(1, max_iters + 1):
            test_out = _run_tests(test_cmd, cwd=cwd)
            history.append({"phase": f"test#{i}", "out": test_out[-2000:]})
            if _tests_passed(test_cmd, test_out):
                return CoderResult(ok=True, iters=i,
                                    final_output=last_edit,
                                    last_test=test_out, history=history)

            if i == max_iters:
                break

            # Feed failure back to Aider
            fix_instr = (
                "The previous edit did not fix all tests. The current test "
                f"output is:\n\n{test_out[-1800:]}\n\n"
                "Please update the code to make the failing tests pass. "
                "Do not weaken or skip tests."
            )
            last_edit = self.tool.edit(fix_instr)
            history.append({"phase": f"edit#{i+1}", "out": last_edit[-1500:]})

        return CoderResult(ok=False, iters=max_iters,
                            final_output=last_edit,
                            last_test=test_out, history=history)


def _run_tests(test_cmd: str, *, cwd: Optional[str] = None,
               timeout: float = 600) -> str:
    """Execute test command (e.g. 'pytest tests/test_x.py -q'). Returns text."""
    try:
        proc = subprocess.run(test_cmd, shell=True, capture_output=True,
                              text=True, cwd=cwd, timeout=timeout)
        return f"$ {test_cmd}\n[exit={proc.returncode}]\n{proc.stdout}\n{proc.stderr}"
    except subprocess.TimeoutExpired:
        return f"$ {test_cmd}\n[TIMEOUT after {timeout}s]"
    except Exception as e:
        return f"$ {test_cmd}\n[error: {e}]"


def _tests_passed(test_cmd: str, output: str) -> bool:
    # Extract exit code from our wrapped output
    import re as _re
    m = _re.search(r"\[exit=(-?\d+)\]", output)
    if m:
        return m.group(1) == "0"
    # Heuristics for common test runners if exit code missing
    out_low = output.lower()
    if "pytest" in test_cmd.lower():
        return "passed" in out_low and "failed" not in out_low
    return "ok" in out_low and "fail" not in out_low
