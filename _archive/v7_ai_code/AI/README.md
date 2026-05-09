# AI — capability development for AIM

Standalone subproject that hosts AI-capability experiments. See
[`CLAUDE.md`](CLAUDE.md) for scope and rules.

## Structure

```
AI/
├── ai/ # python package — modules
│ └── eval_synthesiser.py
├── tests/ # pytest suite for the subproject
├── cases/ # generated eval-case YAMLs (output)
├── artifacts/ # JSONL audit logs, cached embeddings
├── docs/ # design notes
├── CLAUDE.md # scope + rules + module ids
└── README.md # this file
```

## Bootstrap module: eval_synthesiser (S8)

Reads session reflexions from `~/.claude/projects/.../memory/feedback_*.md`
and recent JSONL session events, then generates new YAML eval cases
that probe the failures. Output drops into `AI/cases/` — point the
existing eval harness (`AIM_EVAL_CASES_DIR=~/Desktop/.../AIM/AI/cases`)
to pick them up.
