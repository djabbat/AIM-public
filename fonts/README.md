# AIM — Georgian & Unicode Font Requirements

This directory holds font-related documentation and (optionally) bundled `.ttf`
files for the AIM GUI (`aim_gui.py`).

---

## Why fonts matter

Tkinter uses the system font stack. On a fresh Ubuntu/Debian install, Georgian
script (mkhedruli, Unicode U+10D0–U+10FF) will render as boxes (tofu) unless a
font that covers the Georgian Unicode block is installed.

The same applies to:
- Kazakh Cyrillic / Latin (Қазақша)
- Arabic (العربية)
- Any other non-Latin script used in patient records

---

## Recommended fonts

| Font family | Coverage | Notes |
|-------------|----------|-------|
| **BPG fonts** | Georgian (mkhedruli) | Free, designed for Georgian UI |
| **Sylfaen** | Georgian + Cyrillic + Latin | Bundled with Windows; available separately on Linux |
| **DejaVu Sans** | Broad Unicode incl. Georgian | Pre-installed on most Linux distros |
| **Noto Sans Georgian** | Georgian | Google Noto project — recommended for production |

---

## Installation on Ubuntu / Debian

```bash
# BPG Georgian fonts (recommended for AIM GUI)
sudo apt-get install -y fonts-bpg-georgian-fonts

# Noto Sans (broad Unicode coverage including Georgian)
sudo apt-get install -y fonts-noto fonts-noto-extra

# DejaVu (usually already installed)
sudo apt-get install -y fonts-dejavu-core

# Refresh font cache after installation
fc-cache -fv
```

---

## Tkinter font configuration in aim_gui.py

When constructing the main window, set a Georgian-capable font:

```python
import tkinter as tk
from tkinter import font as tkfont

root = tk.Tk()

# Preferred font order: BPG first, then Noto, then DejaVu as fallback
GEORGIAN_FONT_FAMILY = "BPG Glaho GPL&GNU"   # or "Noto Sans Georgian", "DejaVu Sans"
GEORGIAN_FONT_SIZE   = 12

def make_font(size=GEORGIAN_FONT_SIZE, weight="normal"):
    """Return a Tkinter font guaranteed to render Georgian script."""
    for family in ("BPG Glaho GPL&GNU", "Noto Sans Georgian", "DejaVu Sans", "TkDefaultFont"):
        try:
            f = tkfont.Font(family=family, size=size, weight=weight)
            # Quick check: tkinter will silently fall back if family is unknown
            if family in tkfont.families():
                return f
        except Exception:
            continue
    return tkfont.Font(size=size, weight=weight)  # system default

# Apply to all widgets via option_add (before creating widgets)
root.option_add("*Font", make_font())
```

---

## Verifying Georgian rendering

```python
# Quick terminal check — should print Georgian without tofu:
python3 -c "print('ქართული: ა ბ გ დ ე ვ ზ თ')"

# Check available font families in Tkinter:
python3 -c "import tkinter as tk; r=tk.Tk(); from tkinter import font; print([f for f in font.families() if 'Georgian' in f or 'BPG' in f or 'Noto' in f]); r.destroy()"
```

---

## OCR language packs

For OCR of Georgian-language documents via Tesseract:

```bash
sudo apt-get install -y tesseract-ocr-kat   # Georgian
sudo apt-get install -y tesseract-ocr-rus   # Russian
sudo apt-get install -y tesseract-ocr-kaz   # Kazakh
sudo apt-get install -y tesseract-ocr-ara   # Arabic (optional)
sudo apt-get install -y tesseract-ocr-eng   # English
```

The `config.py` variable `OCR_LANGUAGES` is set to `"rus+kat+kaz+eng"` by default.
