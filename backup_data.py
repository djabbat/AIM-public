#!/usr/bin/env python3
"""
backup_data.py — Зашифрованный бэкап данных пациентов AIM
==========================================================
Архивирует медицинские данные (aim.db + Patients/) в зашифрованный файл.
Шифрование: AES-256-CBC через openssl (pbkdf2, 200 000 итераций).

Хранит последние KEEP_BACKUPS файлов, остальные удаляет.

Пароль генерируется автоматически при первом запуске
и сохраняется в ~/.aim_env как BACKUP_PASSPHRASE.
ВАЖНО: без пароля расшифровать невозможно — не удаляйте ~/.aim_env!

Использование:
  python3 backup_data.py          # создать бэкап
  python3 backup_data.py --list   # показать все бэкапы
  python3 backup_data.py --info   # информация о последнем бэкапе
"""

import os
import secrets
import smtplib
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

AIM_DIR    = Path(__file__).parent
BACKUP_DIR = AIM_DIR / "backups"
ENV_FILE   = Path.home() / ".aim_env"
KEEP_BACKUPS = 14   # хранить N последних бэкапов

# Что архивировать (Patients/ исключены — только БД и конфиг)
BACKUP_TARGETS = [
    AIM_DIR / "aim.db",
    AIM_DIR / "nutrition_rules.json",
    AIM_DIR / "medical_knowledge.json",
    AIM_DIR / "logs",
]


# ── Email ─────────────────────────────────────────────────────

def _read_env() -> dict:
    """Read all key=value pairs from ~/.aim_env."""
    result = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def send_env_email(verbose: bool = True) -> bool:
    """
    Send ~/.aim_env contents to the owner's Gmail.
    Requires GMAIL_ADDRESS and GMAIL_APP_PASSWORD in ~/.aim_env.
    """
    def log(msg):
        if verbose:
            print(msg)

    env = _read_env()
    gmail_addr = env.get("GMAIL_ADDRESS", "")
    app_password = env.get("GMAIL_APP_PASSWORD", "")

    if not gmail_addr or not app_password:
        log("  ⚠️  Email пропущен: нет GMAIL_ADDRESS / GMAIL_APP_PASSWORD в ~/.aim_env")
        return False

    env_content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    msg = MIMEMultipart()
    msg["From"]    = gmail_addr
    msg["To"]      = gmail_addr
    msg["Subject"] = f"AIM backup key — {date_str}"

    body = (
        f"AIM — автоматический бэкап ключей\n"
        f"Дата: {date_str}\n"
        f"{'─' * 40}\n\n"
        f"Содержимое ~/.aim_env:\n\n"
        f"{env_content}\n"
        f"{'─' * 40}\n"
        f"Для расшифровки бэкапа:\n"
        f"  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \\\n"
        f"    -in aim_backup_DATE.tar.gz.enc \\\n"
        f"    -out restored.tar.gz \\\n"
        f"    -pass pass:BACKUP_PASSPHRASE\n"
        f"  tar xzf restored.tar.gz\n"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_addr, app_password)
            server.sendmail(gmail_addr, gmail_addr, msg.as_string())
        log(f"  📧 ~/.aim_env отправлен на {gmail_addr} ✓")
        return True
    except Exception as e:
        log(f"  ❌ Ошибка отправки email: {e}")
        return False


# ── Passphrase ────────────────────────────────────────────────

def _get_or_create_passphrase() -> str:
    """Read BACKUP_PASSPHRASE from ~/.aim_env, create if missing."""
    # Read existing
    lines = []
    passphrase = ""
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.startswith("BACKUP_PASSPHRASE="):
                passphrase = line.split("=", 1)[1].strip()
                break

    if passphrase:
        return passphrase

    # Generate new
    passphrase = secrets.token_urlsafe(32)
    lines.append(f"BACKUP_PASSPHRASE={passphrase}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV_FILE.chmod(0o600)
    print(f"  ⚠️  Новый пароль бэкапа сохранён в {ENV_FILE}")
    print(f"  ⚠️  НЕ УДАЛЯЙТЕ ~/.aim_env — без него расшифровка невозможна!")
    return passphrase


# ── Backup ────────────────────────────────────────────────────

def create_backup(verbose: bool = True) -> Path | None:
    """
    Create an encrypted backup.
    Returns path to the .enc file or None on failure.
    """
    def log(msg):
        if verbose:
            print(msg)

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    enc_path  = BACKUP_DIR / f"aim_backup_{timestamp}.tar.gz.enc"

    log(f"💾 Бэкап данных AIM → {enc_path.name}")

    passphrase = _get_or_create_passphrase()

    # ── Step 1: tar.gz to temp file ───────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False,
                                     dir=BACKUP_DIR) as tmp:
        tmp_path = Path(tmp.name)

    try:
        log("  Архивирование...")
        with tarfile.open(tmp_path, "w:gz") as tar:
            for target in BACKUP_TARGETS:
                if target.exists():
                    arcname = target.name
                    tar.add(target, arcname=arcname)
                    log(f"    + {arcname}")
                else:
                    log(f"    - пропущено (нет): {target.name}")

        size_mb = tmp_path.stat().st_size / 1024 / 1024
        log(f"  Архив: {size_mb:.1f} MB")

        # ── Step 2: encrypt with openssl ──────────────────────
        log("  Шифрование AES-256-CBC...")
        result = subprocess.run(
            [
                "openssl", "enc", "-aes-256-cbc",
                "-pbkdf2", "-iter", "200000",
                "-in",  str(tmp_path),
                "-out", str(enc_path),
                "-pass", f"pass:{passphrase}",
            ],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            log(f"  ❌ Ошибка шифрования: {result.stderr}")
            return None

        enc_size_mb = enc_path.stat().st_size / 1024 / 1024
        log(f"  Зашифровано: {enc_size_mb:.1f} MB → {enc_path.name}")

    finally:
        tmp_path.unlink(missing_ok=True)

    # ── Step 3: rotate old backups ────────────────────────────
    _rotate(verbose=verbose)

    # ── Step 4: email ~/.aim_env to owner ─────────────────────
    send_env_email(verbose=verbose)

    log(f"  ✅ Бэкап создан: {enc_path}")
    return enc_path


def _rotate(verbose: bool = False):
    """Keep only KEEP_BACKUPS most recent backups."""
    files = sorted(BACKUP_DIR.glob("aim_backup_*.tar.gz.enc"))
    to_delete = files[:-KEEP_BACKUPS] if len(files) > KEEP_BACKUPS else []
    for f in to_delete:
        f.unlink()
        if verbose:
            print(f"  🗑  Удалён старый бэкап: {f.name}")


# ── Restore info ─────────────────────────────────────────────

def list_backups() -> list[Path]:
    """Return list of backup files sorted newest-last."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("aim_backup_*.tar.gz.enc"))


def backup_info() -> str:
    """Human-readable info about stored backups."""
    files = list_backups()
    if not files:
        return "Бэкапов нет."
    lines = [f"Бэкапы ({len(files)} из макс. {KEEP_BACKUPS}):"]
    total = 0
    for f in reversed(files):
        sz = f.stat().st_size / 1024 / 1024
        total += sz
        lines.append(f"  {f.name}  ({sz:.1f} MB)")
    lines.append(f"Итого: {total:.1f} MB  →  {BACKUP_DIR}")
    lines.append(f"\nДля расшифровки (после восстановления):")
    lines.append("  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \\")
    lines.append("    -in aim_backup_DATE.tar.gz.enc \\")
    lines.append("    -out restored.tar.gz -pass pass:$(grep BACKUP_PASSPHRASE ~/.aim_env | cut -d= -f2)")
    lines.append("  tar xzf restored.tar.gz")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--list" in args:
        print(backup_info())
        sys.exit(0)

    if "--info" in args:
        print(backup_info())
        sys.exit(0)

    result = create_backup(verbose=True)
    sys.exit(0 if result else 1)
