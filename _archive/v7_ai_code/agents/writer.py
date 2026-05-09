"""agents/writer.py — научное письмо: peer review, manuscript editing,
md→docx pipeline, cover letters, response-to-reviewers.

Делегируется generalist'ом или вызывается напрямую.

Все эмиссии текста с цитированиями проходят через
`agents.kernel.evaluate_l_verifiability` — фабрикованные PMID/DOI
блокируются и помечаются [UNVERIFIED:...].

Public API:
    review(text, *, focus="peer-review", lang="en") → str
    edit(text, *, mode, lang="en")                  → str
    md_to_docx(md_path, docx_path)                  → Path
    cover_letter(manuscript_path, journal, *,       → str
                 author, lang="en")
    response_to_reviewers(manuscript, reviews,
                          *, lang="en")             → str
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from llm import ask, ask_long, ask_deep

log = logging.getLogger("aim.writer")

MD_TO_DOCX = Path.home() / "Desktop" / "AIM-service" / "scripts" / "md_to_docx.py"

SYSTEM_PEER_REVIEW = """You are a senior scientific editor performing peer review.
- Identify methodology concerns, statistical issues, missing controls.
- Flag overstatements or claims not supported by data shown.
- Suggest specific revisions; do NOT rewrite the paper.
- Score: novelty (1-5), rigor (1-5), clarity (1-5), with one-line justification each.
- Final recommendation: accept / minor revision / major revision / reject.
- NEVER fabricate citations. If you reference a paper, use only ones already cited in the manuscript."""

SYSTEM_EDIT = {
    "tighten":  "Tighten this prose: remove redundancy, prefer active voice, keep all facts. Do not add new claims.",
    "academic": "Rewrite in formal academic English suitable for a peer-reviewed journal. Do not change meaning.",
    "translate-en": "Translate to clear academic English. Preserve technical terminology.",
    "abstract": "Compress this section into a 250-word structured abstract: Background / Methods / Results / Conclusions.",
    "polish":   "Light copy-edit: grammar, punctuation, hyphenation. Mark every change with [CHG].",
}


def review(text: str, *, focus: str = "peer-review", lang: str = "en") -> str:
    """Peer-review a manuscript or section. Uses DS-V4-pro (reasoner)."""
    prompt = (
        f"Perform a {focus} of the following manuscript section. "
        f"Output language: {lang}.\n\n"
        f"=== MANUSCRIPT ===\n{text}\n=== END ==="
    )
    out = ask_deep(prompt, system=SYSTEM_PEER_REVIEW)
    return _strip_unverified_citations(out)


SYSTEM_TBPR_REVIEW = (
    "You are running a TRIPLE-BLIND PEER REVIEW (TBPR) cycle on a scientific "
    "article. Produce three distinct reviews — Reviewer A: PARANOID, "
    "Reviewer B: EDITOR, Reviewer C: METHODOLOGIST — plus one combined "
    "editorial verdict, all in the format/style of the TBPR template "
    "provided in the user message. Each reviewer has a different stance:\n"
    "  • PARANOID — fatal flaws, fabricated claims, missing controls, "
    "    citation problems, weak causal logic, biological implausibility.\n"
    "  • EDITOR — fit-for-target-journal, novelty, clarity, structure, "
    "    abstract quality, English, length, figure plan.\n"
    "  • METHODOLOGIST — study design, sample-size logic, statistics plan, "
    "    confounders, falsifiability, pre-registration, mediation/moderation.\n"
    "Combined verdict: REJECT / REVISE_MAJOR / REVISE_MINOR / ACCEPT, "
    "with a 1-paragraph synthesis. Output Markdown. ≥800 words across all "
    "reviews. NEVER fabricate PMIDs/DOIs — only cite what is already in the "
    "article."
)


def tbpr_review(manuscript: str, template: str = "", *,
                lang: str = "en") -> str:
    """Triple-Blind Peer Review (3 reviewers + verdict) of a manuscript.

    `manuscript`: the article text (already loaded from disk by caller).
    `template`:   the TBPR template text (e.g. contents of
                  ~/Desktop/AIM-service/templates/TBPR_article.md). When
                  empty, falls back to a default skeleton baked into the
                  system prompt.

    Uses DS-V4-reasoner with high max_tokens because TBPR output is long
    (10K-25K chars typical). This is the canonical AIM entry point for
    `delegate_writer action=tbpr_review`.
    """
    user_prompt_parts = []
    if template:
        user_prompt_parts.append(
            f"=== TBPR TEMPLATE (follow this structure) ===\n{template}\n"
            f"=== END TEMPLATE ===\n"
        )
    user_prompt_parts.append(
        f"=== ARTICLE TO REVIEW ===\n{manuscript}\n=== END ARTICLE ===\n\n"
        "Now produce the full TBPR review document for this article. "
        f"Output language: {lang}. Format as Markdown."
    )
    user_prompt = "\n".join(user_prompt_parts)
    # ask_deep uses LLM_MAX_TOKENS=16384 default — plenty for full TBPR.
    out = ask_deep(user_prompt, system=SYSTEM_TBPR_REVIEW)
    return _strip_unverified_citations(out)


SYSTEM_APPLY_FIXES = (
    "You are revising a scientific article in response to a TBPR peer "
    "review. Read the original article and the three-reviewer review "
    "document. Apply ALL of the review's recommended fixes that fall under "
    "'Fixable issues' and 'Suggested revisions'. Do NOT make changes the "
    "review didn't request. Do NOT remove substantive content unless "
    "flagged as redundant. Preserve voice and overall structure.\n\n"
    "Output the FULL revised manuscript as Markdown — start with the title, "
    "continue to the end. No commentary, no diff format, no explanation of "
    "changes — just the revised article. Drop-in replacement for the "
    "original .md file."
)


def apply_review_fixes(manuscript: str, review_text: str, *,
                        lang: str = "en") -> str:
    """Apply a TBPR review's recommendations to produce a revised article.

    Returns the revised article text (Markdown, ready to write to disk as
    the next version). Used by `delegate_writer action=apply_fixes`.
    """
    user_prompt = (
        f"=== ORIGINAL ARTICLE ===\n{manuscript}\n=== END ARTICLE ===\n\n"
        f"=== TBPR REVIEW (apply its fixable recommendations) ===\n"
        f"{review_text}\n=== END REVIEW ===\n\n"
        "Now output the revised article. Markdown. Full content. No prose "
        f"commentary outside the article. Output language: {lang}."
    )
    out = ask_deep(user_prompt, system=SYSTEM_APPLY_FIXES)
    return _strip_unverified_citations(out)


def edit(text: str, *, mode: str = "tighten", lang: str = "en") -> str:
    sys = SYSTEM_EDIT.get(mode, SYSTEM_EDIT["tighten"])
    prompt = f"=== INPUT ===\n{text}\n=== END ===\n\nApply: {mode}"
    out = ask(prompt, system=sys, lang=lang)
    return _strip_unverified_citations(out)


def cover_letter(manuscript: str, journal: str, *,
                 author: str = "Jaba Tkemaladze",
                 lang: str = "en") -> str:
    sys = ("You are drafting a cover letter for a journal submission. "
           "1 page max. Sections: opening salutation; one-paragraph summary "
           "of the contribution; one-paragraph fit-with-the-journal argument; "
           "competing-interests + funding statement; closing.")
    prompt = (f"Journal: {journal}\nAuthor: {author}\n\n"
              f"=== MANUSCRIPT ABSTRACT/INTRO ===\n{manuscript[:6000]}\n=== END ===")
    return ask(prompt, system=sys, lang=lang)


def response_to_reviewers(manuscript: str, reviews: str, *,
                          lang: str = "en") -> str:
    sys = ("You are drafting a Response-to-Reviewers letter. "
           "For each reviewer comment: quote it, then give a substantive response, "
           "then state the exact revision made (or rebut with evidence). "
           "Be respectful but firm. Do NOT promise changes you cannot ground in "
           "the manuscript text. Never fabricate new citations.")
    prompt = (f"=== MANUSCRIPT EXCERPT ===\n{manuscript[:8000]}\n=== END ===\n\n"
              f"=== REVIEWERS ===\n{reviews}\n=== END ===")
    return _strip_unverified_citations(ask_long(prompt, system=sys, lang=lang))


def md_to_docx(md_path: str | Path, docx_path: str | Path) -> Path:
    """Convert via the canonical ~/Desktop/AIM-service/scripts/md_to_docx.py.
    Per memory feedback_article_workflow: this is the ONLY allowed pipeline."""
    if not MD_TO_DOCX.exists():
        raise FileNotFoundError(f"canonical converter missing: {MD_TO_DOCX}")
    md_path = Path(md_path).resolve()
    docx_path = Path(docx_path).resolve()
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(MD_TO_DOCX), str(md_path), str(docx_path)],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not docx_path.exists():
        raise RuntimeError(f"md_to_docx failed:\n{proc.stdout}\n{proc.stderr}")
    return docx_path


# ── Internal: enforce citation verifiability ───────────────────────────────


def _strip_unverified_citations(text: str) -> str:
    """Annotate any unverified PMID/DOI in LLM output. Slow path: only runs
    if text actually contains a PMID/DOI pattern (regex pre-check)."""
    import re as _re
    if not _re.search(r"\bPMID[:\s]*\d+|\b10\.\d{4,9}/", text, flags=_re.IGNORECASE):
        return text
    try:
        from tools.literature import enforce_citations
        rep = enforce_citations(text, mode="annotate")
        if rep.rejected:
            log.warning(f"writer: {len(rep.rejected)} unverified citation(s) "
                        f"annotated in output: "
                        f"{[r['value'] for r in rep.rejected]}")
        return rep.text
    except Exception as e:
        log.warning(f"writer: citation verification skipped: {e}")
        return text
