#!/usr/bin/env python3
"""
wearable_importer.py — BLE HealthWearable → AIM
================================================
Читает RR-интервалы с BLE пульсометра (стандарт Bluetooth Heart Rate Profile),
анализирует через ze_ecg.py и сохраняет в папку пациента + SQLite.

Поддерживаемые устройства:
  • Любой пульсометр с Heart Rate Service (UUID 0x180D) — Polar H10, Garmin HRM,
    Wahoo TICKR, CooSpo H808S, и большинство нагрудных датчиков
  • Устройства с RR-интервалами (флаг 0x10 в Heart Rate Measurement 0x2A37)

Использование:
  # Сканировать BLE устройства рядом
  python3 wearable_importer.py --scan

  # Записать 5 минут RR для пациента
  python3 wearable_importer.py --patient Patients/Ivanov_Ivan_2000_01_01 --duration 300

  # Указать устройство по адресу (быстрее — без сканирования)
  python3 wearable_importer.py --address AA:BB:CC:DD:EE:FF --patient Patients/...

  # Сохранить адрес устройства как устройство по умолчанию
  python3 wearable_importer.py --save-device AA:BB:CC:DD:EE:FF

API:
  from wearable_importer import collect_rr, WearableSession
  session = await collect_rr(address, duration_sec=300)
  session.rr_intervals  # list[float] в мс
  session.save_to_patient(patient_dir)
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

AIM_DIR = Path(__file__).parent
sys.path.insert(0, str(AIM_DIR))

from config import get_logger, PATIENTS_DIR

log = get_logger("wearable_importer")

# ── BLE UUIDs (стандарт Bluetooth SIG) ───────────────────────
HR_SERVICE_UUID        = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID    = "00002a37-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID   = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID     = "00002a19-0000-1000-8000-00805f9b34fb"

# ── Default device storage ────────────────────────────────────
_ENV_FILE = os.path.expanduser("~/.aim_env")
_DEVICE_KEY = "WEARABLE_ADDRESS"


def get_saved_address() -> Optional[str]:
    """Read saved BLE device address from ~/.aim_env."""
    if not os.path.exists(_ENV_FILE):
        return None
    for line in open(_ENV_FILE):
        line = line.strip()
        if line.startswith(f"{_DEVICE_KEY}="):
            return line.split("=", 1)[1].strip()
    return None


def save_address(address: str):
    """Save BLE device address to ~/.aim_env."""
    lines = []
    found = False
    if os.path.exists(_ENV_FILE):
        for line in open(_ENV_FILE):
            if line.strip().startswith(f"{_DEVICE_KEY}="):
                lines.append(f"{_DEVICE_KEY}={address}\n")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{_DEVICE_KEY}={address}\n")
    with open(_ENV_FILE, "w") as f:
        f.writelines(lines)
    print(f"✅ Устройство сохранено: {address}")


# ── RR parsing from BLE Heart Rate Measurement ───────────────

def parse_hr_measurement(data: bytes) -> tuple[int, list[float]]:
    """
    Parse Heart Rate Measurement characteristic (0x2A37).
    Returns (heart_rate_bpm, rr_intervals_ms).
    RR intervals in characteristic are in 1/1024 seconds → convert to ms.
    """
    if not data:
        return 0, []

    flags = data[0]
    hr_format_16bit = flags & 0x01   # bit 0: 0=uint8, 1=uint16
    rr_present = flags & 0x10        # bit 4: RR interval present
    energy_present = flags & 0x08    # bit 3: energy expended present

    idx = 1
    if hr_format_16bit:
        hr = int.from_bytes(data[idx:idx+2], "little")
        idx += 2
    else:
        hr = data[idx]
        idx += 1

    if energy_present:
        idx += 2  # skip energy expended (uint16)

    rr_ms = []
    if rr_present:
        while idx + 1 < len(data):
            rr_raw = int.from_bytes(data[idx:idx+2], "little")
            # Convert from 1/1024 s to ms
            rr_ms.append(round(rr_raw / 1024.0 * 1000.0, 1))
            idx += 2

    return hr, rr_ms


# ── Session dataclass ─────────────────────────────────────────

@dataclass
class WearableSession:
    device_name: str
    device_address: str
    started_at: str
    ended_at: str = ""
    rr_intervals: list = field(default_factory=list)   # ms
    hr_samples: list  = field(default_factory=list)    # BPM
    battery_pct: Optional[int] = None
    duration_sec: float = 0.0
    quality: str = "unknown"   # good / fair / poor / insufficient

    def assess_quality(self):
        n = len(self.rr_intervals)
        if n < 30:
            self.quality = "insufficient"
        elif n < 100:
            self.quality = "poor"
        elif n < 200:
            self.quality = "fair"
        else:
            self.quality = "good"

    def save_to_patient(self, patient_dir: str | Path,
                        run_ze: bool = True) -> dict:
        """
        Save session data to patient folder and optionally run Ze analysis.
        Returns dict with paths and Ze report summary.
        """
        patient_dir = Path(patient_dir)
        patient_dir.mkdir(parents=True, exist_ok=True)

        self.assess_quality()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result = {}

        # Raw RR JSON
        raw_path = patient_dir / f"wearable_{ts}.json"
        raw_data = asdict(self)
        raw_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        result["raw_json"] = str(raw_path)
        log.info(f"Raw RR saved: {raw_path.name} ({len(self.rr_intervals)} intervals)")

        # Ze-HRV analysis
        if run_ze and len(self.rr_intervals) >= 30:
            try:
                from ze_ecg import analyze_rr, save_to_patient as ze_save
                report = analyze_rr(self.rr_intervals)
                ze_path = ze_save(report, patient_dir,
                                  source=f"BLE:{self.device_name}")
                result["ze_report"] = str(ze_path)
                result["ze_state"]  = report.metrics.ze_state
                result["ze_v"]      = report.metrics.ze_v
                result["alert"]     = report.alert
                log.info(f"Ze state: {report.metrics.ze_state}, v={report.metrics.ze_v:.3f}")
            except Exception as e:
                log.warning(f"Ze analysis failed: {e}")
                result["ze_error"] = str(e)
        elif len(self.rr_intervals) < 30:
            result["ze_error"] = f"Недостаточно данных: {len(self.rr_intervals)} RR"

        return result


# ── BLE scan ──────────────────────────────────────────────────

async def scan_devices(timeout: float = 8.0) -> list[dict]:
    """Scan for nearby BLE devices with Heart Rate Service."""
    from bleak import BleakScanner

    print(f"🔍 Сканирую BLE устройства ({timeout:.0f} сек)...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)

    hr_devices = []
    other_devices = []

    for addr, (device, adv) in devices.items():
        name = device.name or "Unknown"
        rssi = adv.rssi if hasattr(adv, "rssi") else "?"

        # Check if device advertises Heart Rate Service
        service_uuids = [str(u).lower() for u in (adv.service_uuids or [])]
        has_hr = HR_SERVICE_UUID in service_uuids or "180d" in " ".join(service_uuids)

        info = {"name": name, "address": addr, "rssi": rssi, "has_hr": has_hr}
        if has_hr:
            hr_devices.append(info)
        else:
            other_devices.append(info)

    print(f"\n❤️  Пульсометры (Heart Rate Service):")
    if hr_devices:
        for d in hr_devices:
            print(f"   ✅ {d['name']:30s}  {d['address']}  RSSI: {d['rssi']}")
    else:
        print("   Не найдено. Убедитесь что устройство включено и в режиме сопряжения.")

    print(f"\n📡 Другие BLE устройства ({len(other_devices)}):")
    for d in other_devices[:8]:
        print(f"   {d['name']:30s}  {d['address']}  RSSI: {d['rssi']}")
    if len(other_devices) > 8:
        print(f"   ... и ещё {len(other_devices) - 8}")

    return hr_devices + other_devices


# ── BLE collect ───────────────────────────────────────────────

async def collect_rr(
    address: str,
    duration_sec: float = 300.0,
    on_progress=None,
) -> WearableSession:
    """
    Connect to BLE HR device and collect RR intervals.
    on_progress(elapsed, rr_count, hr) called every second if provided.
    """
    from bleak import BleakClient

    log.info(f"Connecting to {address}...")
    print(f"📡 Подключаюсь к {address}...")

    session = WearableSession(
        device_name="Unknown",
        device_address=address,
        started_at=datetime.now().isoformat(),
    )

    rr_buffer = []
    hr_buffer = []
    start_time = time.monotonic()
    last_progress = 0.0

    def hr_notification(sender, data: bytearray):
        hr, rr_list = parse_hr_measurement(bytes(data))
        if hr > 0:
            hr_buffer.append(hr)
        rr_buffer.extend(rr_list)

    try:
        async with BleakClient(address, timeout=15.0) as client:
            session.device_name = client.address  # fallback
            # Try to get proper name
            try:
                for service in client.services:
                    if "180a" in str(service.uuid):  # Device Information
                        for char in service.characteristics:
                            if "2a29" in str(char.uuid):  # Manufacturer Name
                                val = await client.read_gatt_char(char.uuid)
                                session.device_name = val.decode("utf-8", errors="replace").strip()
            except Exception:
                pass

            # Battery level
            try:
                bat = await client.read_gatt_char(BATTERY_LEVEL_UUID)
                session.battery_pct = bat[0]
                print(f"🔋 Батарея: {bat[0]}%")
            except Exception:
                pass

            # Subscribe to HR notifications
            await client.start_notify(HR_MEASUREMENT_UUID, hr_notification)
            print(f"✅ Подключено. Запись {duration_sec:.0f} сек... (Ctrl+C для остановки)")

            # Progress loop
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= duration_sec:
                    break

                await asyncio.sleep(1.0)
                elapsed = time.monotonic() - start_time

                # Progress callback / print
                if on_progress:
                    hr_now = hr_buffer[-1] if hr_buffer else 0
                    on_progress(elapsed, len(rr_buffer), hr_now)
                elif int(elapsed) % 30 == 0 and elapsed - last_progress >= 29:
                    hr_now = hr_buffer[-1] if hr_buffer else "—"
                    pct = elapsed / duration_sec * 100
                    print(f"  ⏱ {elapsed:.0f}s / {duration_sec:.0f}s  "
                          f"RR: {len(rr_buffer)}  ЧСС: {hr_now} BPM  ({pct:.0f}%)")
                    last_progress = elapsed

            await client.stop_notify(HR_MEASUREMENT_UUID)

    except asyncio.CancelledError:
        print("\n⏹ Запись остановлена.")
    except Exception as e:
        log.error(f"BLE error: {e}")
        print(f"❌ Ошибка BLE: {e}")
        raise

    session.rr_intervals = rr_buffer
    session.hr_samples   = hr_buffer
    session.ended_at     = datetime.now().isoformat()
    session.duration_sec = time.monotonic() - start_time
    session.assess_quality()

    print(f"\n📊 Записано: {len(rr_buffer)} RR-интервалов, "
          f"качество: {session.quality}, "
          f"длительность: {session.duration_sec:.0f}s")

    return session


# ── Interactive patient selector ──────────────────────────────

def select_patient() -> Optional[Path]:
    """Interactive CLI: list patients, return selected folder."""
    base = Path(PATIENTS_DIR)
    patients = sorted(
        [d for d in base.iterdir() if d.is_dir() and d.name != "INBOX"],
        key=lambda d: d.stat().st_mtime, reverse=True
    )
    if not patients:
        print("Нет пациентов в", PATIENTS_DIR)
        return None

    print("\n👥 Пациенты:")
    for i, p in enumerate(patients[:20], 1):
        print(f"  {i:2d}. {p.name}")
    print("   0. Без пациента (сохранить только файл)")
    print()
    try:
        choice = int(input("Выбери номер: ").strip())
    except (ValueError, KeyboardInterrupt):
        return None
    if choice == 0:
        return base / "INBOX"
    if 1 <= choice <= len(patients):
        return patients[choice - 1]
    return None


# ── CLI ───────────────────────────────────────────────────────

async def _main_async(args):
    if args.scan:
        await scan_devices(timeout=args.scan_timeout)
        return

    if args.save_device:
        save_address(args.save_device)
        return

    # Determine address
    address = args.address or get_saved_address()
    if not address:
        print("❌ Не указан адрес устройства.")
        print("   Сначала просканируй: python3 wearable_importer.py --scan")
        print("   Затем сохрани адрес: python3 wearable_importer.py --save-device AA:BB:CC:DD:EE:FF")
        sys.exit(1)

    # Determine patient folder
    if args.patient:
        patient_dir = Path(args.patient)
        if not patient_dir.is_absolute():
            patient_dir = Path(PATIENTS_DIR) / args.patient
    elif args.interactive:
        patient_dir = select_patient()
        if not patient_dir:
            print("Отменено.")
            return
    else:
        patient_dir = Path(PATIENTS_DIR) / "INBOX"
        print(f"ℹ️  Пациент не указан. Данные → {patient_dir}")

    # Collect
    session = await collect_rr(address, duration_sec=args.duration)

    if not session.rr_intervals:
        print("❌ Нет данных. Проверь подключение устройства.")
        sys.exit(1)

    # Save
    result = session.save_to_patient(patient_dir, run_ze=True)

    print(f"\n✅ Сохранено в: {patient_dir.name}")
    print(f"   Файл: {Path(result['raw_json']).name}")
    if "ze_state" in result:
        print(f"   Ze-состояние: {result['ze_state']}  v={result['ze_v']:.3f}")
    if result.get("alert"):
        print(f"   ⚠️  {result['alert']}")
    if "ze_report" in result:
        print(f"   Ze-отчёт: {Path(result['ze_report']).name}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="AIM Wearable BLE Importer — сбор RR-интервалов с пульсометра"
    )
    parser.add_argument("--scan",         action="store_true",
                        help="Сканировать BLE устройства")
    parser.add_argument("--scan-timeout", type=float, default=8.0,
                        help="Время сканирования в секундах (default: 8)")
    parser.add_argument("--address",      help="BLE адрес устройства (AA:BB:CC:DD:EE:FF)")
    parser.add_argument("--save-device",  metavar="ADDRESS",
                        help="Сохранить адрес как устройство по умолчанию")
    parser.add_argument("--patient",      help="Папка пациента (имя или полный путь)")
    parser.add_argument("--duration",     type=float, default=300.0,
                        help="Длительность записи в секундах (default: 300 = 5 мин)")
    parser.add_argument("--interactive",  action="store_true",
                        help="Интерактивный выбор пациента из списка")
    args = parser.parse_args()

    try:
        asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        print("\nОстановлено.")


if __name__ == "__main__":
    main()
