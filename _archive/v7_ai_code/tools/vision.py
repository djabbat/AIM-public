"""tools/vision.py — image / PDF page understanding.

Native multimodal: send PNG/JPG/PDF page directly to vision-capable model
(Claude Opus 4.7 if ANTHROPIC_API_KEY set, else DeepSeek-V4 vision).

Public API:
    see(path, prompt, *, page=0, model_hint=None)  → str
    pdf_page_to_png(pdf_path, page, out_path)       → Path

The generalist exposes this via the `view_image` tool.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.vision")


def _mime_for(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    if mt and mt.startswith("image/"):
        return mt
    suf = path.suffix.lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp"}.get(suf, "image/png")


def pdf_page_to_png(pdf_path: str | Path, page: int = 0,
                    out_path: Optional[Path] = None,
                    dpi: int = 150) -> Path:
    """Render a PDF page → PNG. Requires pymupdf (already in requirements)."""
    import pymupdf  # type: ignore
    pdf_path = Path(pdf_path).expanduser()
    out_path = Path(out_path) if out_path else \
               pdf_path.with_suffix(f".p{page}.png")
    doc = pymupdf.open(str(pdf_path))
    try:
        if page >= len(doc):
            raise ValueError(f"page {page} out of range (PDF has {len(doc)} pages)")
        pg = doc[page]
        mat = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)
        pix = pg.get_pixmap(matrix=mat)
        pix.save(str(out_path))
    finally:
        doc.close()
    return out_path


# ── Backends ────────────────────────────────────────────────────────────────


def _see_claude(image_b64: str, mime: str, prompt: str, system: str = "") -> Optional[str]:
    """Anthropic vision via the Claude messages API."""
    from llm import _claude_chat, anthropic_available
    if not anthropic_available():
        return None
    images = [{
        "type": "image",
        "source": {"type": "base64", "media_type": mime, "data": image_b64},
    }]
    out = _claude_chat(prompt, system=system, images=images, temperature=0)
    return out or None


def _see_deepseek(image_b64: str, mime: str, prompt: str, system: str = "") -> Optional[str]:
    """DeepSeek-V4 vision endpoint (OpenAI-compatible image_url with data URI)."""
    from llm import _deepseek, _breaker_for, _limiter_for, _record_llm_error
    from config import DEEPSEEK_API_KEY, Models
    if not DEEPSEEK_API_KEY:
        return None
    _breaker_for("deepseek").before_call()
    _limiter_for("deepseek").acquire()
    data_uri = f"data:{mime};base64,{image_b64}"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]})
    try:
        resp = _deepseek().chat.completions.create(
            model=Models.DS_CHAT, messages=messages, temperature=0,
            max_tokens=4096,
        )
        _breaker_for("deepseek").on_success()
        return resp.choices[0].message.content.strip()
    except Exception as e:
        _breaker_for("deepseek").on_failure()
        _record_llm_error("deepseek", e)
        log.warning(f"DS-V4 vision failed: {e}")
        return None


# ── Public ──────────────────────────────────────────────────────────────────


def see(path: str | Path, prompt: str, *,
        page: int = 0, system: str = "",
        model_hint: Optional[str] = None) -> str:
    """Look at an image (or PDF page) and answer a question about it.

    Order of preference (default 2026-04-30):
        Claude Opus 4.7 vision  →  DeepSeek-V4 vision  →  OCR fallback.

    `model_hint` ∈ {'claude', 'deepseek', None} forces a backend.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"ERROR: file not found: {p}"

    # PDF → render the requested page first
    if p.suffix.lower() == ".pdf":
        try:
            p = pdf_page_to_png(p, page=page)
        except Exception as e:
            return f"ERROR: PDF render failed: {e}"

    # Encode
    try:
        raw = p.read_bytes()
    except Exception as e:
        return f"ERROR: read failed: {e}"
    if len(raw) > 20 * 1024 * 1024:
        return f"ERROR: image too large ({len(raw) // 1024} KB > 20 MB cap)"
    b64 = base64.b64encode(raw).decode("ascii")
    mime = _mime_for(p)

    # Backend chain
    backends = []
    if model_hint == "claude":
        backends = [_see_claude]
    elif model_hint == "deepseek":
        backends = [_see_deepseek]
    else:
        backends = [_see_claude, _see_deepseek]

    for fn in backends:
        out = fn(b64, mime, prompt, system=system)
        if out:
            return out

    # OCR fallback (last resort, only for png/jpg)
    return _ocr_fallback(p, prompt)


def _ocr_fallback(p: Path, prompt: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(p))
        if not text.strip():
            return f"ERROR: no vision provider available and OCR returned empty text"
        # Wrap in LLM analysis if any text was extracted
        from llm import ask
        return ask(f"Question: {prompt}\n\nOCR text from image:\n{text[:6000]}",
                   system="Answer based ONLY on the OCR text below; mention if it's incomplete.")
    except Exception as e:
        return f"ERROR: vision unavailable and OCR fallback failed: {e}"
