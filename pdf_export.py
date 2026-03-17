#!/usr/bin/env python3
"""
pdf_export.py — Экспорт отчёта пациента в PDF
===============================================
Использование:
  python3 pdf_export.py Patients/Ivanov_Ivan_2000_01_01/
  python3 pdf_export.py --all          # все пациенты с готовым анализом

API:
  from pdf_export import export_patient
  path = export_patient("/path/to/patient/folder")  # → Path к PDF
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

AIM_DIR = Path(__file__).parent
sys.path.insert(0, str(AIM_DIR))

from config import PATIENTS_DIR, get_logger

log = get_logger("pdf_export")

# ── Fonts: use built-in reportlab or try to register Noto ────

def _register_fonts():
    """Register Unicode-capable font. Falls back to Helvetica if unavailable."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Search for a CID/TTF font that covers Cyrillic + Georgian + Latin
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        os.path.expanduser("~/.fonts/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("AIMFont", path))
                bold_path = path.replace("Regular", "Bold").replace(".ttf", "-Bold.ttf")
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont("AIMFont-Bold", bold_path))
                else:
                    pdfmetrics.registerFont(TTFont("AIMFont-Bold", path))
                return "AIMFont", "AIMFont-Bold"
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold"


# ── Color palette ─────────────────────────────────────────────

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

C_DARK    = colors.HexColor("#1a2332")
C_ACCENT  = colors.HexColor("#2d6a9f")
C_LIGHT   = colors.HexColor("#e8f4fd")
C_GREEN   = colors.HexColor("#2e7d32")
C_RED     = colors.HexColor("#c62828")
C_ORANGE  = colors.HexColor("#ef6c00")
C_GRAY    = colors.HexColor("#757575")
C_WHITE   = colors.white
C_BORDER  = colors.HexColor("#cfd8dc")


# ── Lab status colors ─────────────────────────────────────────

STATUS_COLOR = {
    "normal":        C_GREEN,
    "low":           C_ORANGE,
    "high":          C_ORANGE,
    "critical_low":  C_RED,
    "critical_high": C_RED,
    "unknown":       C_GRAY,
}

STATUS_LABEL = {
    "normal":        "НОРМА",
    "low":           "↓ НИЖЕ",
    "high":          "↑ ВЫШЕ",
    "critical_low":  "⚠ КРИТИЧЕСКИ НИЗКО",
    "critical_high": "⚠ КРИТИЧЕСКИ ВЫСОКО",
    "unknown":       "—",
}


# ── Patient data loader ───────────────────────────────────────

FOLDER_RE = re.compile(
    r'^([A-Za-zА-Яа-яЁёა-ჿ\-]+)_([A-Za-zА-Яа-яЁёა-ჿ\-]+)_(\d{4})_(\d{2})_(\d{2})$'
)


def _load_patient_data(folder: Path) -> dict:
    """Load all available data from patient folder."""
    data = {"folder": folder, "name": "", "dob": "", "analysis": "",
            "labs": [], "ze": None, "numerology": None}

    # Name from folder
    m = FOLDER_RE.match(folder.name)
    if m:
        data["name"] = f"{m.group(1)} {m.group(2)}"
        data["dob"] = f"{m.group(3)}-{m.group(4)}-{m.group(5)}"
    else:
        data["name"] = folder.name

    # AI analysis
    analysis_file = folder / "_ai_analysis.txt"
    if analysis_file.exists():
        data["analysis"] = analysis_file.read_text(encoding="utf-8", errors="replace")

    # Lab results from JSON snapshot
    import json
    lab_snap = folder / "_lab_history.json"
    if lab_snap.exists():
        try:
            history = json.loads(lab_snap.read_text(encoding="utf-8"))
            if history:
                # Take most recent snapshot
                latest = max(history, key=lambda x: x.get("date", ""))
                data["labs"] = latest.get("results", [])
        except Exception:
            pass

    # Ze-HRV
    ze_file = folder / "ze_hrv.json"
    if ze_file.exists():
        try:
            data["ze"] = json.loads(ze_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Numerology
    try:
        from numerology import from_patient_folder
        data["numerology"] = from_patient_folder(str(folder))
    except Exception:
        pass

    return data


# ── PDF builder ───────────────────────────────────────────────

def export_patient(folder_path: str, output_path: Optional[str] = None) -> Path:
    """
    Generate PDF report for a patient.
    Returns path to generated PDF.
    """
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable, KeepTogether)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    folder = Path(folder_path)
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder_path}")

    data = _load_patient_data(folder)

    # Output path
    if output_path:
        pdf_path = Path(output_path)
    else:
        pdf_path = folder / f"_report_{datetime.now().strftime('%Y%m%d')}.pdf"

    FONT, FONT_BOLD = _register_fonts()

    # ── Styles ───────────────────────────────────────────────
    def style(name, font=FONT, size=10, color=C_DARK, bold=False,
              align=TA_LEFT, leading=None, space_before=0, space_after=2):
        return ParagraphStyle(
            name,
            fontName=FONT_BOLD if bold else font,
            fontSize=size,
            textColor=color,
            alignment=align,
            leading=leading or size * 1.3,
            spaceBefore=space_before,
            spaceAfter=space_after,
        )

    s_title    = style("title",    size=20, bold=True,  color=C_WHITE,  align=TA_CENTER)
    s_subtitle = style("subtitle", size=11, color=C_WHITE, align=TA_CENTER)
    s_h1       = style("h1",       size=13, bold=True,  color=C_ACCENT, space_before=8, space_after=4)
    s_h2       = style("h2",       size=11, bold=True,  color=C_DARK,   space_before=5, space_after=2)
    s_body     = style("body",     size=9,  color=C_DARK, leading=13)
    s_small    = style("small",    size=8,  color=C_GRAY)
    s_alert    = style("alert",    size=9,  color=C_RED, bold=True)
    s_footer   = style("footer",   size=7.5, color=C_GRAY, align=TA_CENTER)

    # ── Document ──────────────────────────────────────────────
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=12*mm, bottomMargin=15*mm,
        title=f"AIM — {data['name']}",
        author="AIM — Dr. Jaba Tkemaladze",
    )

    W = A4[0] - 36*mm  # usable width

    story = []

    # ── Header banner ─────────────────────────────────────────
    header_data = [[
        Paragraph("🏥 AIM — Integrative Medicine", s_title),
    ]]
    header_table = Table(header_data, colWidths=[W])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_ACCENT),
        ("ROUNDEDCORNERS", [4]),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4*mm))

    # ── Patient info block ────────────────────────────────────
    dob_display = data["dob"] or "—"
    generated   = datetime.now().strftime("%d.%m.%Y %H:%M")
    info_rows = [
        [Paragraph(f"<b>Пациент:</b> {data['name']}", s_body),
         Paragraph(f"<b>Дата рождения:</b> {dob_display}", s_body)],
        [Paragraph(f"<b>Папка:</b> {folder.name}", s_small),
         Paragraph(f"<b>Отчёт сгенерирован:</b> {generated}", s_small)],
    ]
    info_table = Table(info_rows, colWidths=[W*0.55, W*0.45])
    info_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_LIGHT),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5*mm))

    # ── Lab results table ─────────────────────────────────────
    if data["labs"]:
        story.append(Paragraph("📊 Лабораторные показатели", s_h1))
        story.append(HRFlowable(width=W, color=C_ACCENT, thickness=0.5))
        story.append(Spacer(1, 2*mm))

        # Re-evaluate labs for current patient demographics
        try:
            from lab_reference import evaluate
            from patient_intake import _patient_demographics
            sex, age_group = _patient_demographics(folder)
        except Exception:
            sex, age_group = "*", "adult"

        lab_header = [
            Paragraph("<b>Показатель</b>", style("lh", bold=True, size=8, color=C_WHITE)),
            Paragraph("<b>Значение</b>",   style("lh", bold=True, size=8, color=C_WHITE, align=TA_CENTER)),
            Paragraph("<b>Норма</b>",       style("lh", bold=True, size=8, color=C_WHITE, align=TA_CENTER)),
            Paragraph("<b>Статус</b>",      style("lh", bold=True, size=8, color=C_WHITE, align=TA_CENTER)),
        ]
        lab_rows = [lab_header]
        for item in data["labs"]:
            pid   = item.get("param_id", "")
            val   = item.get("value", "")
            unit  = item.get("unit", "")
            name  = item.get("name", pid)
            status = item.get("status", "unknown")

            # Get reference range string
            ref_str = "—"
            try:
                from lab_reference import get_reference
                ref = get_reference(pid, sex, age_group)
                if ref:
                    ref_str = f"{ref.low}–{ref.high} {ref.unit}"
            except Exception:
                pass

            sc = STATUS_COLOR.get(status, C_GRAY)
            sl = STATUS_LABEL.get(status, "—")
            lab_rows.append([
                Paragraph(name, style("lc", size=8)),
                Paragraph(f"{val} {unit}", style("lc", size=8, align=TA_CENTER)),
                Paragraph(ref_str, style("lc", size=8, color=C_GRAY, align=TA_CENTER)),
                Paragraph(sl, style("lc", size=8, color=sc, align=TA_CENTER, bold=(status not in ("normal", "unknown")))),
            ])

        col_w = [W*0.38, W*0.22, W*0.24, W*0.16]
        lab_table = Table(lab_rows, colWidths=col_w, repeatRows=1)
        lab_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), C_ACCENT),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_LIGHT]),
            ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, C_BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ]))
        story.append(lab_table)
        story.append(Spacer(1, 5*mm))

    # ── Ze-HRV section ────────────────────────────────────────
    if data["ze"]:
        ze = data["ze"]
        m  = ze.get("metrics", {})
        story.append(Paragraph("💓 Ze-HRV Анализ", s_h1))
        story.append(HRFlowable(width=W, color=C_ACCENT, thickness=0.5))
        story.append(Spacer(1, 2*mm))

        ze_state = m.get("ze_state", "—")
        ze_color = {"healthy": C_GREEN, "stress": C_ORANGE,
                    "arrhythmia": C_RED, "tachyarrhythmia": C_RED,
                    "bradyarrhythmia": C_RED}.get(ze_state, C_GRAY)

        ze_rows = [
            ["Ze-скорость (v)",      f"{m.get('ze_v', '—'):.3f}" if isinstance(m.get('ze_v'), float) else "—"],
            ["Ze-τ (стабильность)",  str(m.get("ze_tau", "—"))],
            ["RMSSD",                f"{m.get('rmssd', '—')} мс"],
            ["SDNN",                 f"{m.get('sdnn', '—')} мс"],
            ["pNN50",                f"{m.get('pnn50', '—')} %"],
            ["ЧСС",                  f"{m.get('mean_hr', '—')} BPM"],
        ]
        ze_table_data = [[
            Paragraph(r[0], style("zk", size=8, bold=True)),
            Paragraph(r[1], style("zv", size=8)),
        ] for r in ze_rows]

        ze_table = Table(ze_table_data, colWidths=[W*0.4, W*0.6])
        ze_table.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_LIGHT]),
            ("BOX",            (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID",      (0, 0), (-1, -1), 0.3, C_BORDER),
            ("TOPPADDING",     (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 3),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ]))

        story.append(Paragraph(
            f"Состояние: <font color='#{ze_color.hexval()[1:]}'><b>{ze_state.upper()}</b></font>",
            style("zestate", size=10, bold=True)
        ))
        story.append(Spacer(1, 2*mm))
        story.append(ze_table)

        if ze.get("alert"):
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph(ze["alert"], s_alert))
        story.append(Spacer(1, 5*mm))

    # ── Numerology section ────────────────────────────────────
    if data["numerology"]:
        nu = data["numerology"]
        story.append(Paragraph("🔢 Нумерологический профиль", s_h1))
        story.append(HRFlowable(width=W, color=C_ACCENT, thickness=0.5))
        story.append(Spacer(1, 2*mm))

        nu_rows = [
            ["Число жизненного пути",  str(nu["life_path"]) + (" ✨" if nu["is_master"] else "")],
            ["Описание",                nu["life_path_meaning"]],
            ["Число дня рождения",      str(nu["birthday_number"])],
            ["Число отношения",         str(nu["attitude_number"])],
            ["Персональный год",        f"{nu['personal_year']} — {nu['personal_year_meaning']}"],
        ]
        nu_data = [[
            Paragraph(r[0], style("nk", size=8, bold=True)),
            Paragraph(r[1], style("nv", size=8)),
        ] for r in nu_rows]

        nu_table = Table(nu_data, colWidths=[W*0.35, W*0.65])
        nu_table.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_LIGHT]),
            ("BOX",            (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID",      (0, 0), (-1, -1), 0.3, C_BORDER),
            ("TOPPADDING",     (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 3),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ]))
        story.append(nu_table)
        story.append(Spacer(1, 5*mm))

    # ── AI Analysis text ──────────────────────────────────────
    if data["analysis"]:
        story.append(Paragraph("🧠 AI Медицинский анализ", s_h1))
        story.append(HRFlowable(width=W, color=C_ACCENT, thickness=0.5))
        story.append(Spacer(1, 2*mm))

        # Split by sections (lines with ===)
        for line in data["analysis"].split("\n"):
            line = line.rstrip()
            if not line:
                story.append(Spacer(1, 1.5*mm))
            elif line.startswith("===") or line.startswith("---"):
                story.append(HRFlowable(width=W, color=C_BORDER, thickness=0.3))
            elif line.isupper() and len(line) > 4:
                story.append(Paragraph(line, s_h2))
            elif line.startswith("  ") or line.startswith("•"):
                story.append(Paragraph(line.strip(), style("bi", size=8.5, space_before=1)))
            else:
                # Escape XML special chars
                safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(safe, s_body))

    # ── Footer ────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width=W, color=C_BORDER, thickness=0.5))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        f"AIM — Integrative Medicine Assistant | Dr. Jaba Tkemaladze | "
        f"+995 555 185 161 | Сгенерировано: {generated}",
        s_footer
    ))
    story.append(Paragraph(
        "⚠ Данный отчёт является вспомогательным инструментом и не заменяет "
        "клинического суждения врача.",
        style("disclaimer", size=6.5, color=C_GRAY, align=TA_CENTER)
    ))

    # ── Build ──────────────────────────────────────────────────
    doc.build(story)
    log.info(f"PDF exported: {pdf_path}")
    return pdf_path


# ── Batch export ──────────────────────────────────────────────

def export_all(patients_dir: Optional[str] = None) -> list:
    """Export PDFs for all patients that have _ai_analysis.txt."""
    base = Path(patients_dir or PATIENTS_DIR)
    results = []
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.name.startswith(".") or folder.name == "INBOX":
            continue
        if not (folder / "_ai_analysis.txt").exists():
            continue
        try:
            pdf = export_patient(str(folder))
            results.append({"patient": folder.name, "pdf": str(pdf), "ok": True})
            print(f"  ✅ {folder.name}")
        except Exception as e:
            results.append({"patient": folder.name, "error": str(e), "ok": False})
            print(f"  ❌ {folder.name}: {e}")
    return results


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AIM — PDF Report Export")
    parser.add_argument("folder", nargs="?", help="Patient folder path")
    parser.add_argument("--all",    action="store_true", help="Export all patients")
    parser.add_argument("--output", help="Output PDF path (single patient only)")
    args = parser.parse_args()

    if args.all:
        print("📄 Экспорт всех пациентов...")
        res = export_all()
        ok  = sum(1 for r in res if r["ok"])
        print(f"\n✅ {ok}/{len(res)} PDF экспортировано в папки пациентов.")
    elif args.folder:
        folder = Path(args.folder)
        if not folder.is_absolute():
            folder = Path(PATIENTS_DIR) / args.folder
        print(f"📄 Экспорт {folder.name}...")
        pdf = export_patient(str(folder), args.output)
        print(f"✅ {pdf}")
    else:
        parser.print_help()
