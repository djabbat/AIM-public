#!/usr/bin/env python3
"""
ze_ecg.py — Ze-анализ RR-интервалов (ЭКГ/HRV)

Теория Ze: RR-интервал длиннее предыдущего = 0 (T-событие, покой/стабильность)
           RR-интервал короче предыдущего   = 1 (S-событие, активность/переход)

Ze-скорость v = доля S-событий в окне.
Здоровое сердце: v ≈ 0.35–0.45
Аритмия: v → крайние значения (< 0.2 или > 0.6)
Стресс/тахикардия: v → 0.5 (максимальный хаос)

Входные данные: список RR-интервалов в миллисекундах.
Источники: ЭКГ (.csv), HRV-носимые устройства (.json), EDF.

Интеграция: AIM → patient_intake.py, telegram_bot.py, HealthWearable
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Ze константы
# ─────────────────────────────────────────────────────────────────────────────

ZE_V_HEALTHY_LOW  = 0.35   # нижняя граница нормы
ZE_V_HEALTHY_HIGH = 0.45   # верхняя граница нормы
ZE_V_STAR         = 0.40   # целевая Ze-скорость (оптимум)
ZE_SHANNON_LIMIT  = 0.9161 # Z_Ze при p=0.5 — теоретический предел

WINDOW_SIZE = 30           # окно скользящего расчёта (события)
MIN_RR_MS   = 300          # минимально допустимый RR (200 BPM)
MAX_RR_MS   = 2000         # максимально допустимый RR (30 BPM)


# ─────────────────────────────────────────────────────────────────────────────
# Результирующие структуры
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ZeMetrics:
    """Ze-метрики по всему сегменту RR."""
    # Ze
    ze_v: float            # Ze-скорость [0..1]
    ze_tau: int            # накопленные T-события (стабильность)
    ze_impedance: float    # Z_Ze = p/(1-p)
    ze_chi: float          # χ_Ze = 1 - Z_Ze (Ze-cheating index)
    ze_stream_len: int     # длина Ze-потока
    ze_state: str          # "healthy" | "stress" | "arrhythmia" | "bradyarrhythmia" | "insufficient_data"

    # Стандартные HRV
    rmssd: float           # мс — парасимпатическая активность
    sdnn: float            # мс — общая вариабельность
    pnn50: float           # % RR с разницей >50мс
    mean_rr: float         # мс — средний RR
    mean_hr: float         # BPM — средняя ЧСС
    nn_count: int          # количество RR (после фильтрации)

    # Контекст
    segment_sec: float     # длина сегмента в секундах
    quality: str           # "good" | "fair" | "poor"


@dataclass
class ZeWindow:
    """Ze-метрики в одном скользящем окне."""
    idx: int               # индекс последнего RR в окне
    ze_v: float
    ze_tau: int
    rmssd_window: float


@dataclass
class ZeReport:
    """Полный Ze-отчёт для AIM."""
    metrics: ZeMetrics
    windows: list[ZeWindow]
    interpretation: str    # текстовая интерпретация для врача
    alert: Optional[str]   # None или строка тревоги


# ─────────────────────────────────────────────────────────────────────────────
# Ядро: Ze-поток
# ─────────────────────────────────────────────────────────────────────────────

def rr_to_ze_stream(rr_ms: list[float]) -> list[int]:
    """
    Преобразует список RR-интервалов в Ze-поток (бинарный).
    rr[i] > rr[i-1] → 0 (T-событие, сердце замедлилось — покой)
    rr[i] < rr[i-1] → 1 (S-событие, сердце ускорилось — активность)
    rr[i] == rr[i-1] → 0 (T-событие по умолчанию)
    """
    stream = []
    for i in range(1, len(rr_ms)):
        stream.append(1 if rr_ms[i] < rr_ms[i - 1] else 0)
    return stream


def ze_velocity(stream: list[int], start: int = 0, end: Optional[int] = None) -> float:
    """Ze-скорость v = доля S-событий в сегменте потока."""
    seg = stream[start:end]
    if not seg:
        return 0.0
    return sum(seg) / len(seg)


def ze_tau(stream: list[int]) -> int:
    """Накопленные T-события (длительность последней T-серии + общая сумма T)."""
    return stream.count(0)


def ze_impedance(v: float) -> float:
    """Z_Ze = p/(1-p). При v=0.5 → ∞ (хаос). При v→0 → 0 (полный покой)."""
    p = max(1e-9, min(1 - 1e-9, v))
    return p / (1.0 - p)


def ze_chi(v: float) -> float:
    """χ_Ze = 1 - Z_Ze. Нормальные клетки/сердце: χ_Ze ≈ 0.6–0.8."""
    z = ze_impedance(v)
    return 1.0 - z


# ─────────────────────────────────────────────────────────────────────────────
# Стандартные HRV
# ─────────────────────────────────────────────────────────────────────────────

def _filter_rr(rr_ms: list[float]) -> list[float]:
    """Удаляет физиологически невозможные RR (артефакты)."""
    return [r for r in rr_ms if MIN_RR_MS <= r <= MAX_RR_MS]


def compute_hrv(rr_ms: list[float]) -> dict:
    """Стандартные HRV метрики временной области."""
    nn = _filter_rr(rr_ms)
    n = len(nn)
    if n < 2:
        return {"rmssd": 0.0, "sdnn": 0.0, "pnn50": 0.0,
                "mean_rr": 0.0, "mean_hr": 0.0, "nn_count": n}

    diffs = [abs(nn[i] - nn[i - 1]) for i in range(1, n)]
    rmssd = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    sdnn  = statistics.stdev(nn) if n > 1 else 0.0
    pnn50 = 100.0 * sum(1 for d in diffs if d > 50) / len(diffs)
    mean_rr = statistics.mean(nn)
    mean_hr = 60000.0 / mean_rr if mean_rr > 0 else 0.0

    return {
        "rmssd": round(rmssd, 2),
        "sdnn":  round(sdnn, 2),
        "pnn50": round(pnn50, 2),
        "mean_rr": round(mean_rr, 2),
        "mean_hr": round(mean_hr, 1),
        "nn_count": n,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Классификация Ze-состояния
# ─────────────────────────────────────────────────────────────────────────────

def classify_ze_state(v: float, rmssd: float, mean_hr: float, nn_count: int) -> str:
    if nn_count < 10:
        return "insufficient_data"
    if mean_hr > 120 and v > 0.50:
        return "tachyarrhythmia"
    if mean_hr < 45 and v < 0.25:
        return "bradyarrhythmia"
    if v < 0.20:
        return "bradyarrhythmia"
    if v > 0.55:
        return "arrhythmia"
    if rmssd < 15 or (0.48 <= v <= 0.55):
        return "stress"
    if ZE_V_HEALTHY_LOW <= v <= ZE_V_HEALTHY_HIGH:
        return "healthy"
    if 0.25 <= v < ZE_V_HEALTHY_LOW:
        return "low_variability"
    return "borderline"


def data_quality(nn_count: int, segment_sec: float) -> str:
    if nn_count >= 100 and segment_sec >= 120:
        return "good"
    if nn_count >= 30 and segment_sec >= 30:
        return "fair"
    return "poor"


# ─────────────────────────────────────────────────────────────────────────────
# Скользящие окна
# ─────────────────────────────────────────────────────────────────────────────

def sliding_windows(rr_ms: list[float], stream: list[int], size: int = WINDOW_SIZE) -> list[ZeWindow]:
    nn = _filter_rr(rr_ms)
    windows = []
    for end in range(size, len(stream) + 1):
        seg = stream[end - size:end]
        v = ze_velocity(seg)
        tau = seg.count(0)
        # RMSSD окна
        rr_win = nn[max(0, end - size - 1):end]
        diffs = [abs(rr_win[i] - rr_win[i - 1]) for i in range(1, len(rr_win))]
        rmssd_w = math.sqrt(sum(d * d for d in diffs) / len(diffs)) if diffs else 0.0
        windows.append(ZeWindow(
            idx=end,
            ze_v=round(v, 4),
            ze_tau=tau,
            rmssd_window=round(rmssd_w, 2),
        ))
    return windows


# ─────────────────────────────────────────────────────────────────────────────
# Интерпретация
# ─────────────────────────────────────────────────────────────────────────────

def interpret(m: ZeMetrics) -> tuple[str, Optional[str]]:
    state_ru = {
        "healthy":           "Норма — сердечный Ze-ритм в пределах физиологического диапазона",
        "stress":            "Стресс / сниженная вариабельность — тонус парасимпатики снижен",
        "arrhythmia":        "Аритмия — нарушение ритма Ze-потока, рекомендована ЭКГ",
        "tachyarrhythmia":   "Тахиаритмия — высокая ЧСС + хаотичный Ze-поток",
        "bradyarrhythmia":   "Брадиаритмия — низкая ЧСС + монотонный Ze-поток",
        "low_variability":   "Низкая вариабельность — возможна усталость, медикаменты или ваготония",
        "borderline":        "Пограничные значения — контроль в динамике",
        "insufficient_data": "Недостаточно данных для оценки (< 10 RR-интервалов)",
    }.get(m.ze_state, "Неизвестное состояние")

    lines = [
        f"Ze-скорость: v = {m.ze_v:.3f} (норма 0.35–0.45, оптимум 0.40)",
        f"Ze-импеданс: Z_Ze = {m.ze_impedance:.3f}",
        f"Ze-cheating: χ_Ze = {m.ze_chi:.3f}",
        f"Ze-τ (стабильность): {m.ze_tau} T-событий из {m.ze_stream_len}",
        f"RMSSD = {m.rmssd} мс  |  SDNN = {m.sdnn} мс  |  pNN50 = {m.pnn50}%",
        f"Средняя ЧСС = {m.mean_hr} BPM  |  Средний RR = {m.mean_rr} мс",
        f"Длина сегмента: {m.segment_sec:.1f} с  |  N = {m.nn_count} RR  |  Качество: {m.quality}",
        f"",
        f"Интерпретация: {state_ru}",
    ]
    interpretation = "\n".join(lines)

    alert = None
    if m.ze_state in ("arrhythmia", "tachyarrhythmia", "bradyarrhythmia"):
        alert = f"⚠️ Ze-ТРЕВОГА: {state_ru}. v={m.ze_v:.3f}, ЧСС={m.mean_hr} BPM. Рекомендована ЭКГ."
    elif m.rmssd < 15:
        alert = f"⚠️ RMSSD={m.rmssd} мс — критически низкая вариабельность (норма >20 мс)."
    elif m.mean_hr > 100:
        alert = f"⚠️ Тахикардия: ЧСС={m.mean_hr} BPM."
    elif m.mean_hr < 50:
        alert = f"⚠️ Брадикардия: ЧСС={m.mean_hr} BPM."

    return interpretation, alert


# ─────────────────────────────────────────────────────────────────────────────
# Главная функция анализа
# ─────────────────────────────────────────────────────────────────────────────

def analyze_rr(rr_ms: list[float]) -> ZeReport:
    """
    Полный Ze-анализ списка RR-интервалов (мс).
    Возвращает ZeReport с метриками, окнами, интерпретацией и тревогами.
    """
    nn = _filter_rr(rr_ms)
    stream = rr_to_ze_stream(nn)

    hrv = compute_hrv(nn)
    v   = ze_velocity(stream) if stream else 0.0
    tau = ze_tau(stream)
    z   = ze_impedance(v)
    chi = ze_chi(v)

    segment_sec = sum(nn) / 1000.0
    state   = classify_ze_state(v, hrv["rmssd"], hrv["mean_hr"], hrv["nn_count"])
    quality = data_quality(hrv["nn_count"], segment_sec)

    metrics = ZeMetrics(
        ze_v=round(v, 4),
        ze_tau=tau,
        ze_impedance=round(z, 4),
        ze_chi=round(chi, 4),
        ze_stream_len=len(stream),
        ze_state=state,
        rmssd=hrv["rmssd"],
        sdnn=hrv["sdnn"],
        pnn50=hrv["pnn50"],
        mean_rr=hrv["mean_rr"],
        mean_hr=hrv["mean_hr"],
        nn_count=hrv["nn_count"],
        segment_sec=round(segment_sec, 1),
        quality=quality,
    )

    windows = sliding_windows(nn, stream)
    interpretation, alert = interpret(metrics)

    return ZeReport(metrics=metrics, windows=windows,
                    interpretation=interpretation, alert=alert)


# ─────────────────────────────────────────────────────────────────────────────
# Парсеры входных форматов
# ─────────────────────────────────────────────────────────────────────────────

def from_csv(path: str | Path, column: str = "rr_ms") -> list[float]:
    """Читает RR-интервалы из CSV (колонка rr_ms или первая числовая)."""
    import csv
    path = Path(path)
    rr = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and column in reader.fieldnames:
            for row in reader:
                try:
                    rr.append(float(row[column]))
                except (ValueError, KeyError):
                    pass
        else:
            f.seek(0)
            reader2 = csv.reader(f)
            next(reader2, None)  # skip header
            for row in reader2:
                for cell in row:
                    try:
                        val = float(cell.strip())
                        if MIN_RR_MS <= val <= MAX_RR_MS:
                            rr.append(val)
                            break
                    except ValueError:
                        pass
    return rr


def from_wearable_json(path: str | Path) -> list[float]:
    """
    Читает RR из HealthWearable JSON-пакетов:
    [{..., "rr_ms": [800, 790, ...]}, ...]
    или {"rr_ms": [...]}
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    rr = []
    if isinstance(data, list):
        for packet in data:
            val = packet.get("rr_ms")
            if isinstance(val, list):
                rr.extend(val)
            elif isinstance(val, (int, float)):
                rr.append(float(val))
    elif isinstance(data, dict):
        val = data.get("rr_ms", [])
        if isinstance(val, list):
            rr.extend(val)
    return [float(r) for r in rr if MIN_RR_MS <= float(r) <= MAX_RR_MS]


def from_plain_list(values: list) -> list[float]:
    """Список чисел → отфильтрованные RR в мс."""
    return [float(v) for v in values if MIN_RR_MS <= float(v) <= MAX_RR_MS]


# ─────────────────────────────────────────────────────────────────────────────
# AIM-интеграция: сохранить результат в папку пациента
# ─────────────────────────────────────────────────────────────────────────────

def save_to_patient(report: ZeReport, patient_dir: str | Path, source: str = "") -> Path:
    """
    Сохраняет Ze-отчёт в папку пациента AIM + в SQLite БД.
    patient_dir: ~/Desktop/AIM/Patients/SURNAME_NAME_YYYY_MM_DD/
    Создаёт: patient_dir/ze_hrv.json + ze_hrv_report.txt
    """
    import re as _re
    patient_dir = Path(patient_dir)
    patient_dir.mkdir(parents=True, exist_ok=True)

    # JSON — машиночитаемый
    json_path = patient_dir / "ze_hrv.json"
    payload = {
        "source": source,
        "metrics": asdict(report.metrics),
        "windows": [asdict(w) for w in report.windows[-50:]],  # последние 50 окон
        "alert": report.alert,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # TXT — для врача
    txt_path = patient_dir / "ze_hrv_report.txt"
    txt_path.write_text(
        f"=== Ze-HRV Анализ ===\n"
        f"Источник: {source}\n\n"
        f"{report.interpretation}\n"
        f"\n{'⚠️  ТРЕВОГА: ' + report.alert if report.alert else '✅ Тревог нет'}\n",
        encoding="utf-8",
    )

    # SQLite — записать в БД
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import db as _db
        _db.init_db()

        # Найти или создать запись пациента по имени папки
        folder_re = _re.compile(
            r'^([A-Za-zА-Яа-яЁёა-ჿ\-]+)_([A-Za-zА-Яа-яЁёა-ჿ\-]+)_(\d{4})_(\d{2})_(\d{2})$'
        )
        m = folder_re.match(patient_dir.name)
        patient_id = None
        if m:
            sur, nam, y, mo, d = m.groups()
            patient_id = _db.upsert_patient(
                surname=sur, name=nam,
                folder_path=str(patient_dir),
                dob=f"{y}-{mo}-{d}"
            )
        else:
            # Folder name without DOB — upsert by name only
            parts = patient_dir.name.split("_")
            if len(parts) >= 2:
                patient_id = _db.upsert_patient(
                    surname=parts[0], name=parts[1],
                    folder_path=str(patient_dir)
                )

        if patient_id:
            # Build metrics dict matching db.save_ze_hrv expected keys
            m_obj = report.metrics
            metrics_dict = {
                "ze_v":     m_obj.ze_v,
                "ze_tau":   m_obj.ze_tau,
                "ze_state": m_obj.ze_state,
                "rmssd":    m_obj.rmssd,
                "sdnn":     m_obj.sdnn,
                "pnn50":    m_obj.pnn50,
                "mean_hr":  m_obj.mean_hr,
                "mean_rr":  m_obj.mean_rr,
                "quality":  m_obj.quality,
            }
            _db.save_ze_hrv(
                patient_id=patient_id,
                metrics=metrics_dict,
                source=source,
            )
    except Exception as _e:
        pass  # DB write is non-critical — file is already saved

    return json_path


# ─────────────────────────────────────────────────────────────────────────────
# CLI / быстрый тест
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.suffix == ".json":
            rr = from_wearable_json(path)
        else:
            rr = from_csv(path)
        source = str(path)
    else:
        # Демо-данные: синус-аритмия (норма, v ≈ 0.40)
        import random
        random.seed(42)
        base = 850
        rr = []
        for _ in range(200):
            base += random.gauss(0, 30)
            base = max(500, min(1200, base))
            rr.append(round(base))
        source = "demo"

    report = analyze_rr(rr)
    print(report.interpretation)
    if report.alert:
        print(f"\n{report.alert}")
    print(f"\nJSON preview: ze_v={report.metrics.ze_v}, state={report.metrics.ze_state}")
