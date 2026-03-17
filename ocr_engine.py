#!/usr/bin/env python3
"""
OCR engine for medical screenshots.
Priority: tesseract → rapidocr → fallback message.
Supports: Russian, Georgian, Kazakh, English.
Preprocessing: upscale, deskew, adaptive threshold, sharpen.
"""

import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

_ocr_lock = threading.Lock()

from config import OCR_LANGS, OCR_MIN_DPI, get_logger

log = get_logger("ocr_engine")

try:
    from PIL import Image, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ── Image preprocessing ───────────────────────────────────────

def preprocess_for_ocr(img: "Image.Image") -> "Image.Image":
    """
    Prepare medical screenshot for best OCR accuracy:
    1. Grayscale
    2. Upscale to ≥1200px wide
    3. Deskew (±5° correction)
    4. Sharpen + contrast
    5. Binarize
    """
    img = img.convert("L")

    # Upscale if small
    w, h = img.size
    if w < 1200:
        scale = 1200 / w
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    img = _deskew(img)
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = ImageEnhance.Sharpness(img).enhance(2.5)
    # Simple binarize — improves Cyrillic recognition on noisy backgrounds
    img = img.point(lambda p: 255 if p > 140 else 0)

    return img


def _deskew(img: "Image.Image") -> "Image.Image":
    """Detect & correct skew by maximising horizontal projection variance."""
    try:
        import numpy as np
        best_angle, best_var = 0.0, -1.0
        for angle in [a * 0.5 for a in range(-10, 11)]:
            rotated = img.rotate(angle, expand=False, fillcolor=255)
            var = float(np.array(rotated).sum(axis=1).astype(float).var())
            if var > best_var:
                best_var, best_angle = var, angle
        if abs(best_angle) > 0.3:
            img = img.rotate(best_angle, expand=True, fillcolor=255)
    except ImportError:
        pass
    return img


# ── Tesseract ─────────────────────────────────────────────────

def _try_tesseract(img: "Image.Image") -> Optional[str]:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        text = pytesseract.image_to_string(img, lang=OCR_LANGS,
                                            config="--psm 6 --oem 3")
        if text.strip():
            return text.strip()
        # Retry with Russian only
        text = pytesseract.image_to_string(img, lang="rus", config="--psm 6")
        return text.strip() or None
    except Exception as e:
        log.debug(f"tesseract: {e}")
        return None


# ── RapidOCR (fallback) ───────────────────────────────────────

def _try_rapidocr(image_path: str) -> Optional[str]:
    try:
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(image_path)
        if result:
            return "\n".join(item[1] for item in result if item and len(item) > 1)
        return None
    except Exception as e:
        log.debug(f"rapidocr: {e}")
        return None


# ── Main entry point ──────────────────────────────────────────

# Thread-safe LRU cache (lru_cache is not thread-safe for concurrent async callers)
_ocr_cache: dict = {}

def ocr_image(image_path: str) -> Optional[str]:
    """
    Extract text from image. Cached by path for the session.
    Returns None on failure (never returns error strings — callers must check).
    Pipeline: preprocess → tesseract → rapidocr → None.
    Thread-safe via _ocr_lock.
    """
    with _ocr_lock:
        if image_path in _ocr_cache:
            return _ocr_cache[image_path]

    if not os.path.exists(image_path):
        log.warning(f"OCR: file not found: {image_path}")
        return None

    log.debug(f"OCR: {Path(image_path).name}")
    result: Optional[str] = None

    if HAS_PIL:
        try:
            img_proc = preprocess_for_ocr(Image.open(image_path))
            text = _try_tesseract(img_proc)
            if text:
                log.debug(f"  tesseract: {len(text)} chars")
                result = text
        except Exception as e:
            log.debug(f"  preprocess failed: {e}")

    if result is None:
        text = _try_rapidocr(image_path)
        if text:
            log.debug(f"  rapidocr: {len(text)} chars")
            result = text

    if result is None:
        log.warning(f"OCR failed for {Path(image_path).name}. "
                    "Check: sudo apt-get install tesseract-ocr tesseract-ocr-rus tesseract-ocr-kat")

    with _ocr_lock:
        _ocr_cache[image_path] = result
    return result


def ocr_folder(folder_path: str,
               extensions=(".jpg", ".jpeg", ".png", ".webp")) -> dict:
    """OCR all images in folder. Returns {filename: text}."""
    return {
        f.name: ocr_image(str(f))
        for f in sorted(Path(folder_path).iterdir())
        if f.suffix.lower() in extensions
    }


def is_medical_screenshot(text: str) -> bool:
    keywords = [
        "гемоглобин", "hgb", "wbc", "тромбоциты", "plt",
        "глюкоза", "glucose", "холестерин", "ldl", "hdl",
        "tsh", "t3", "t4", "ферритин", "ferritin",
        "витамин", "vitamin", "d3", "b12",
        "норма", "reference", "mmol", "ммоль", "мг/дл",
        "анализ", "лаборатория", "ჰემოგლობინი",
    ]
    tl = text.lower()
    return sum(1 for kw in keywords if kw in tl) >= 2
