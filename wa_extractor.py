#!/usr/bin/env python3
"""
AIM — WhatsApp Auto-Extractor
==============================
Connects to the running WhatsApp Desktop Linux via Chrome DevTools Protocol (CDP).
Extracts patient chats (contacts with P/П/პ separator) and their media.
Saves everything to ~/AIM/Patients/INBOX/ for automatic intake.

USAGE:
  1. Launch WhatsApp with debug port (see below)
  2. python3 wa_extractor.py

HOW TO LAUNCH WITH DEBUG PORT:
  /home/oem/whatsapp-desktop-linux/build/linux-unpacked/whatsapp-desktop-linux \
      --remote-debugging-port=9222 &

Or add it to the .desktop launcher permanently.
"""

import os
import re
import sys
import json
import time
import shutil
import base64
import hashlib
import requests
import websocket
import threading
import subprocess
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CDP_HOST, CDP_PORT, INBOX_DIR, WA_BINARY, get_logger
log = get_logger("wa_extractor")

# Patient separator pattern
PATIENT_RE = re.compile(
    r'^([A-Za-zА-Яа-яЁёა-ჿ\-]+)\s+[PПპ]\s+([A-Za-zА-Яа-яЁёა-ჿ\-]+)$'
)


# ── CDP client ────────────────────────────────────────────────

class CDPClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_message,
            on_error=self._on_error,
        )
        self._thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self._thread.start()
        time.sleep(0.5)

    def _on_message(self, ws, msg):
        data = json.loads(msg)
        mid = data.get("id")
        if mid and mid in self._pending:
            self._pending[mid]["result"] = data
            self._pending[mid]["event"].set()

    def _on_error(self, ws, err):
        pass

    def call(self, method: str, params: dict = None, timeout: int = 30):
        with self._lock:
            self._id += 1
            mid = self._id
        evt = threading.Event()
        self._pending[mid] = {"event": evt, "result": None}
        self.ws.send(json.dumps({"id": mid, "method": method,
                                  "params": params or {}}))
        evt.wait(timeout)
        result = self._pending.pop(mid, {}).get("result", {})
        return result

    def eval_js(self, js: str, timeout: int = 30) -> dict:
        """Evaluate JavaScript in the page context."""
        result = self.call("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True,
            "awaitPromise": True,
            "timeout": timeout * 1000,
        }, timeout=timeout + 5)
        return result.get("result", {}).get("result", {})

    def close(self):
        self.ws.close()


# ── CDP connection helpers ─────────────────────────────────────

def get_cdp_targets():
    try:
        r = requests.get(f"{CDP_HOST}/json", timeout=3)
        return r.json()
    except Exception:
        return []


def find_wa_target(targets: list) -> dict | None:
    for t in targets:
        url = t.get("url", "")
        if "web.whatsapp.com" in url and t.get("type") == "page":
            return t
    return None


def ensure_wa_running() -> bool:
    """Check if WhatsApp is running with CDP. If not, launch it."""
    targets = get_cdp_targets()
    if find_wa_target(targets):
        return True

    # Check if running without CDP
    result = subprocess.run(["pgrep", "-f", "whatsapp-desktop-linux"],
                             capture_output=True, text=True)
    if result.returncode == 0:
        print("⚠  WhatsApp запущен, но без отладочного порта.")
        print("   Закройте его и запустите командой:")
        print(f'   {WA_BINARY} --remote-debugging-port={CDP_PORT} &')
        print("   Затем подождите пока WhatsApp загрузится и запустите снова.")
        return False

    # Launch with CDP
    print(f"Запуск WhatsApp с отладочным портом {CDP_PORT}...")
    subprocess.Popen(
        [WA_BINARY, f"--remote-debugging-port={CDP_PORT}",
         "--no-sandbox", "--start-hidden"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print("Ожидание загрузки WhatsApp Web (до 30 сек)...")
    for i in range(30):
        time.sleep(1)
        targets = get_cdp_targets()
        if find_wa_target(targets):
            print("✓ WhatsApp загружен")
            time.sleep(3)  # Extra wait for WA JS to initialize
            return True
        print(f"  {i+1}/30...", end="\r")
    print("\n✗ Таймаут — WhatsApp не загрузился")
    return False


# ── WhatsApp JS API ───────────────────────────────────────────

# Inject a lightweight helper that uses WhatsApp's internal Store
WA_INIT_JS = """
(function() {
    // Try to find WhatsApp's internal module system
    if (window._AIM_ready) return 'already_init';

    // WA Web exposes Store via require or window.require
    const req = window.require || window.webpackChunkwhatsapp_web_client;
    if (!req) return 'no_require';

    try {
        // Try standard WA Web module access
        window._AIM_Store = {};

        // Method 1: Direct require (older WA Web)
        try {
            window._AIM_Store.Chat = require('WAWebChatCollection').default ||
                                      require('WAWebChatModel').default;
        } catch(e) {}

        // Method 2: Webpack module search
        if (!window._AIM_Store.Chat) {
            const modules = window.webpackChunkwhatsapp_web_client;
            if (modules && modules.push) {
                let chatStore = null;
                modules.push([['_AIM_probe'], {}, (__webpack_require__) => {
                    const moduleIds = Object.keys(__webpack_require__.m || {});
                    for (const id of moduleIds) {
                        try {
                            const mod = __webpack_require__(id);
                            if (mod && mod.default && typeof mod.default.getModelsArray === 'function') {
                                const models = mod.default.getModelsArray();
                                if (models.length > 0 && models[0].id) {
                                    chatStore = mod.default;
                                    break;
                                }
                            }
                        } catch(e) {}
                    }
                }]);
                window._AIM_Store.Chat = chatStore;
            }
        }

        window._AIM_ready = !!window._AIM_Store.Chat;
        return window._AIM_ready ? 'ok' : 'store_not_found';
    } catch(e) {
        return 'error: ' + e.message;
    }
})()
"""

WA_GET_CONTACTS_JS = """
(function() {
    // Get all chats and find patient contacts (P/П/პ separator)
    const pattern = /^([\\w\\u0400-\\u04ff\\u10d0-\\u10ff\\-]+)\\s+[PП\\u10de]\\s+([\\w\\u0400-\\u04ff\\u10d0-\\u10ff\\-]+)$/;

    // Try different ways to get chat list
    let chats = [];

    // Method 1: window.Store
    if (window._AIM_Store && window._AIM_Store.Chat) {
        chats = window._AIM_Store.Chat.getModelsArray() || [];
    }

    // Method 2: direct search in WA's module store
    if (chats.length === 0) {
        try {
            const allChats = [];
            window.webpackChunkwhatsapp_web_client && window.webpackChunkwhatsapp_web_client.push([
                ['_AIM_chats'], {}, (__webpack_require__) => {
                    Object.keys(__webpack_require__.m || {}).forEach(id => {
                        try {
                            const mod = __webpack_require__(id);
                            ['default', 'Chat', 'Chats', 'ChatStore'].forEach(key => {
                                const m = mod && mod[key];
                                if (m && typeof m.getModelsArray === 'function') {
                                    const models = m.getModelsArray();
                                    if (models && models.length > 0) {
                                        allChats.push(...models);
                                    }
                                }
                            });
                        } catch(e) {}
                    });
                }
            ]);
            chats = [...new Set(allChats)];
        } catch(e) {}
    }

    if (chats.length === 0) return {error: 'no_chats_found'};

    const patients = [];
    for (const chat of chats) {
        const name = chat.name || chat.formattedTitle || (chat.contact && chat.contact.name) || '';
        const m = pattern.exec(name.trim());
        if (m) {
            patients.push({
                id: chat.id ? chat.id.toString() : '',
                name: name,
                last_name: m[1],
                first_name: m[2],
                unread: chat.unreadCount || 0,
                last_message: chat.lastMessage ? {
                    body: chat.lastMessage.body || '',
                    timestamp: chat.lastMessage.t || 0,
                } : null,
            });
        }
    }
    return {total_chats: chats.length, patients: patients};
})()
"""


def get_patient_messages_js(chat_id: str, limit: int = 500) -> str:
    return f"""
(async function() {{
    const chatId = {json.dumps(chat_id)};
    const limit = {limit};

    // Find the chat
    let targetChat = null;
    const pattern = /^([\\w\\u0400-\\u04ff\\u10d0-\\u10ff\\-]+)\\s+[PП\\u10de]\\s+/;

    try {{
        window.webpackChunkwhatsapp_web_client && window.webpackChunkwhatsapp_web_client.push([
            ['_AIM_msgs_' + chatId.slice(-6)], {{}}, (__webpack_require__) => {{
                Object.keys(__webpack_require__.m || {{}}).forEach(id => {{
                    try {{
                        const mod = __webpack_require__(id);
                        ['default', 'Chat', 'Chats'].forEach(key => {{
                            const m = mod && mod[key];
                            if (m && typeof m.get === 'function') {{
                                const c = m.get(chatId);
                                if (c) targetChat = c;
                            }}
                        }});
                    }} catch(e) {{}}
                }});
            }}
        ]);
    }} catch(e) {{}}

    if (!targetChat) return {{error: 'chat_not_found', id: chatId}};

    // Load messages
    const msgs = targetChat.msgs ? targetChat.msgs.getModelsArray() : [];
    const result = [];
    for (const msg of msgs.slice(-limit)) {{
        result.push({{
            id: msg.id ? msg.id.toString() : '',
            from: msg.from ? msg.from.toString() : '',
            to: msg.to ? msg.to.toString() : '',
            body: msg.body || '',
            type: msg.type || 'chat',
            timestamp: msg.t || 0,
            hasMedia: !!msg.hasMedia,
            mediaType: msg.type || '',
            caption: msg.caption || '',
        }});
    }}
    return {{messages: result, count: result.length}};
}})()
"""


# ── Media download via CDP ─────────────────────────────────────

def download_media_js(msg_id: str) -> str:
    return f"""
(async function() {{
    const msgId = {json.dumps(msg_id)};
    try {{
        let msg = null;
        window.webpackChunkwhatsapp_web_client && window.webpackChunkwhatsapp_web_client.push([
            ['_AIM_media_' + msgId.slice(-6)], {{}}, (__webpack_require__) => {{
                Object.keys(__webpack_require__.m || {{}}).forEach(id => {{
                    try {{
                        const mod = __webpack_require__(id);
                        if (mod && mod.downloadMedia && typeof mod.downloadMedia === 'function') {{
                            window._AIM_downloadMedia = mod.downloadMedia;
                        }}
                        if (mod && mod.default && mod.default.downloadMedia) {{
                            window._AIM_downloadMedia = mod.default.downloadMedia;
                        }}
                    }} catch(e) {{}}
                }});
            }}
        ]);

        if (window._AIM_downloadMedia) {{
            // Find message by ID and download
            return {{status: 'download_function_found'}};
        }}
        return {{status: 'download_not_available'}};
    }} catch(e) {{
        return {{error: e.message}};
    }}
}})()
"""


# ── Main extractor ────────────────────────────────────────────

def extract_patients(cdp: CDPClient, verbose: bool = True) -> list:
    """Find all patient chats in WhatsApp."""
    if verbose:
        print("Поиск пациентов в WhatsApp...", end=" ", flush=True)

    result = cdp.eval_js(WA_GET_CONTACTS_JS, timeout=20)

    if result.get("type") == "object" and result.get("value"):
        data = result["value"]
    elif result.get("type") == "string":
        print(f"\n  Ответ: {result.get('value')}")
        return []
    else:
        # Try to get subproperties
        data = {}

    if "error" in data:
        if verbose:
            print(f"\n  ⚠ {data['error']}")
        return []

    patients = data.get("patients", [])
    total = data.get("total_chats", 0)

    if verbose:
        print(f"✓ ({total} чатов, {len(patients)} пациентов)")

    return patients


def save_chat_to_inbox(patient: dict, messages: list,
                        inbox_dir: str = INBOX_DIR) -> str:
    """Save extracted chat as a text file in INBOX."""
    os.makedirs(inbox_dir, exist_ok=True)

    last_name = patient["last_name"]
    first_name = patient["first_name"]
    contact_name = patient["name"]

    # Build filename
    fname = f"WhatsApp Chat with {contact_name}.txt"
    fpath = os.path.join(inbox_dir, fname)

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(f"[WhatsApp Export — Auto-extracted by AIM]\n")
        f.write(f"Contact: {contact_name}\n\n")

        for msg in sorted(messages, key=lambda m: m.get("timestamp", 0)):
            ts = msg.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts).strftime("%d.%m.%y, %H:%M:%S") if ts else "??"
            sender = contact_name if msg.get("from", "").startswith(
                last_name.lower()) else "Вы"
            body = msg.get("body", "") or f"[{msg.get('type', 'media')}]"
            if msg.get("caption"):
                body = f"{msg['caption']}\n{body}"
            f.write(f"[{dt}] {sender}: {body}\n")

    return fpath


def run_extraction(auto_import: bool = True, verbose: bool = True):
    """Main extraction flow."""
    print("═" * 55)
    print("  AIM — Извлечение данных из WhatsApp Desktop")
    print("═" * 55)

    # 1. Ensure WhatsApp is running with CDP
    if not ensure_wa_running():
        return

    # 2. Find WhatsApp page
    targets = get_cdp_targets()
    wa_target = find_wa_target(targets)
    if not wa_target:
        print("✗ Страница WhatsApp Web не найдена в CDP")
        print("  Убедитесь, что WhatsApp запущен и авторизован")
        return

    ws_url = wa_target.get("webSocketDebuggerUrl")
    if not ws_url:
        print("✗ WebSocket URL не найден")
        return

    if verbose:
        print(f"✓ Подключение к WhatsApp Web ({wa_target.get('url', '')[:40]})")

    # 3. Connect
    try:
        cdp = CDPClient(ws_url)
    except Exception as e:
        print(f"✗ Ошибка подключения CDP: {e}")
        return

    # 4. Extract patients
    patients = extract_patients(cdp, verbose=verbose)

    if not patients:
        print("\nПациентов не найдено.")
        print("Убедитесь, что контакты названы в формате: ФАМИЛИЯ П ИМЯ")
        cdp.close()
        return

    print(f"\nНайденные пациенты:")
    for i, p in enumerate(patients, 1):
        print(f"  {i}. {p['name']}  (непрочитано: {p.get('unread', 0)})")

    # 5. Extract messages for each patient
    saved_files = []
    for patient in patients:
        chat_id = patient.get("id", "")
        if not chat_id:
            continue

        print(f"\n  Извлечение: {patient['name']}...", end=" ", flush=True)
        msg_result = cdp.eval_js(get_patient_messages_js(chat_id), timeout=30)

        messages = []
        if msg_result.get("type") == "object":
            data = msg_result.get("value", {})
            messages = data.get("messages", [])

        print(f"✓ {len(messages)} сообщений")

        if messages or True:  # Save even if 0 messages (to trigger intake)
            fpath = save_chat_to_inbox(patient, messages)
            saved_files.append(fpath)
            print(f"    → {fpath}")

    cdp.close()

    # 6. Run intake pipeline
    if auto_import and saved_files:
        print(f"\nЗапуск intake pipeline для {len(saved_files)} пациентов...")
        from patient_intake import process_inbox
        process_inbox(INBOX_DIR)

    print("\n✓ Готово")
    return saved_files


def patch_wa_launcher():
    """
    Add --remote-debugging-port to the WhatsApp .desktop launcher.
    This makes CDP available every time WA starts.
    """
    desktop_files = [
        os.path.expanduser("~/.local/share/applications/whatsapp-desktop-linux.desktop"),
        "/usr/share/applications/whatsapp-desktop-linux.desktop",
    ]
    found = None
    for f in desktop_files:
        if os.path.exists(f):
            found = f
            break

    if not found:
        # Check in build dir
        build_desktop = "/home/oem/whatsapp-desktop-linux/data/io.github.mimbrero.WhatsAppDesktop.desktop"
        if os.path.exists(build_desktop):
            found = build_desktop

    if not found:
        print("Desktop файл WhatsApp не найден, создаю новый...")
        found = os.path.expanduser("~/.local/share/applications/whatsapp-desktop-linux.desktop")

    content = ""
    if os.path.exists(found):
        content = open(found).read()

    flag = f"--remote-debugging-port={CDP_PORT}"
    if flag in content:
        print(f"✓ Флаг {flag} уже есть в {found}")
        return

    if "Exec=" in content:
        import re
        content = re.sub(
            r'(Exec=\S+)(.*)',
            lambda m: f'{m.group(1)} {flag}{m.group(2)}',
            content
        )
    else:
        content = f"""[Desktop Entry]
Type=Application
Name=WhatsApp
Exec={WA_BINARY} {flag}
Icon=/home/oem/whatsapp-desktop-linux/data/icons/hicolor/512x512/apps/io.github.mimbrero.WhatsAppDesktop.png
Terminal=false
Categories=Network;InstantMessaging;
"""

    os.makedirs(os.path.dirname(found), exist_ok=True)
    with open(found, "w") as f:
        f.write(content)

    print(f"✓ Обновлён launcher: {found}")
    print(f"  Добавлен флаг: {flag}")
    print("  Перезапустите WhatsApp для применения")


# ── CLI ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AIM — WhatsApp extractor")
    parser.add_argument("--patch-launcher", action="store_true",
                        help="Add --remote-debugging-port to WA launcher (run once)")
    parser.add_argument("--no-import", action="store_true",
                        help="Extract only, don't run intake pipeline")
    parser.add_argument("--list-only", action="store_true",
                        help="Only list patient contacts, don't extract messages")
    args = parser.parse_args()

    if args.patch_launcher:
        patch_wa_launcher()
        sys.exit(0)

    if args.list_only:
        if not ensure_wa_running():
            sys.exit(1)
        targets = get_cdp_targets()
        wa_target = find_wa_target(targets)
        if wa_target:
            cdp = CDPClient(wa_target["webSocketDebuggerUrl"])
            patients = extract_patients(cdp)
            for p in patients:
                print(f"  {p['name']}")
            cdp.close()
        sys.exit(0)

    run_extraction(auto_import=not args.no_import)
