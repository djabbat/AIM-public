#!/usr/bin/env python3
"""gdrive_backup.py — бэкап данных пациентов в Google Drive.

Требует:
  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Настройка (одноразово):
  1. Идти в https://console.cloud.google.com/
  2. Создать проект → Enable Google Drive API
  3. OAuth consent screen (External) → добавить scope .../auth/drive.file
  4. Credentials → Create OAuth client ID → Desktop app
  5. Скачать JSON → сохранить как ~/.aim_gdrive_credentials.json

Первый запуск откроет браузер для OAuth.
Токен сохранится в ~/.aim_gdrive_token.json.
"""

import json
import os
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_PATH = Path.home() / ".aim_gdrive_credentials.json"
TOKEN_PATH = Path.home() / ".aim_gdrive_token.json"
GDRIVE_FOLDER_NAME = "AIM_Patients"


def _get_service():
    """Возвращает авторизованный Google Drive service."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Файл credentials не найден: {CREDENTIALS_PATH}\n"
                    "Скачай OAuth client ID JSON из Google Cloud Console → "
                    "сохрани как ~/.aim_gdrive_credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service) -> str:
    """Находит или создаёт папку AIM_Patients в Google Drive."""
    query = (
        f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )
    resp = service.files().list(q=query, spaces="drive", fields="files(id,name)").execute()
    folders = resp.get("files", [])
    if folders:
        return folders[0]["id"]

    folder_meta = {
        "name": GDRIVE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=folder_meta, fields="id").execute()
    return folder["id"]


def backup_to_gdrive(patient_id: str, data: dict, local_backup_dir: str = "") -> str:
    """Загружает JSON пациента в Google Drive.

    Returns:
        Ссылку на файл или сообщение об ошибке.
    """
    try:
        service = _get_service()
        folder_id = _get_or_create_folder(service)

        filename = f"{patient_id}_{data.get('full_name', 'unknown')}.json".replace(" ", "_")

        # Upload
        from googleapiclient.http import MediaFileUpload
        import tempfile

        # Write temp file
        tmp = Path(tempfile.gettempdir()) / filename
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        file_meta = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(str(tmp), mimetype="application/json", resumable=True)
        uploaded = service.files().create(body=file_meta, media_body=media, fields="id").execute()

        tmp.unlink(missing_ok=True)

        return f"https://drive.google.com/file/d/{uploaded['id']}/view"
    except ImportError:
        return "GDrive не настроен: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Ошибка GDrive: {e}"


def check_gdrive_ready() -> bool:
    """Проверяет, настроен ли Google Drive."""
    return CREDENTIALS_PATH.exists()


if __name__ == "__main__":
    # Тест
    print("GDrive credentials:", "✅" if check_gdrive_ready() else "❌ (нет ~/.aim_gdrive_credentials.json)")
    if check_gdrive_ready():
        test_data = {"full_name": "Тестовый Пациент", "test": True}
        result = backup_to_gdrive("test123", test_data)
        print("Тестовый бэкап:", result)
