#!/usr/bin/env python3
"""Extract code blocks from _*.md artifacts into real files."""
import re, pathlib

ROOT = pathlib.Path.home() / "Desktop" / "AIM" / "DiffDiagnosis"

# Pattern: matches ```lang ... ``` blocks and tries to find a path comment in the first 3 lines.
BLOCK_RE = re.compile(r"```(\w+)\n(.*?)```", re.DOTALL)
PATH_HINT_RE = re.compile(r"^[#/]+\s*([\w./_-]+\.(?:rs|exs|ex|toml|json))\s*$", re.MULTILINE)


def extract(artifact_path: pathlib.Path, default_dir: pathlib.Path) -> list[pathlib.Path]:
    text = artifact_path.read_text(encoding="utf-8")
    written = []
    for m in BLOCK_RE.finditer(text):
        lang, body = m.group(1), m.group(2)
        # search first 3 lines for path hint
        first_lines = "\n".join(body.splitlines()[:3])
        path_match = PATH_HINT_RE.search(first_lines)
        if path_match:
            rel = path_match.group(1)
            # strip the hint line
            body = re.sub(r"^[#/]+\s*[\w./_-]+\.(?:rs|exs|ex|toml|json)\s*\n", "", body, count=1)
        else:
            # default name from artifact + lang
            ext = {"toml": "toml", "rust": "rs", "elixir": "ex", "json": "json"}.get(lang, "txt")
            rel = f"{artifact_path.stem.lstrip('_')}.{ext}"
        target = default_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.strip() + "\n", encoding="utf-8")
        written.append(target)
        print(f"  → {target.relative_to(ROOT)}  ({len(body)} B)")
    return written


def main() -> None:
    print("=== Backend ===")
    extract(ROOT / "backend" / "_main_rs.md",   ROOT / "backend")
    extract(ROOT / "backend" / "_engine_rs.md", ROOT / "backend")
    extract(ROOT / "backend" / "_types_rs.md",  ROOT / "backend")

    print("\n=== Frontend ===")
    extract(ROOT / "frontend" / "_phoenix.md",  ROOT / "frontend")


if __name__ == "__main__":
    main()
