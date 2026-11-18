#!/usr/bin/env python3
"""android-agent setup: connect to an Android phone and remember it.

Works on Windows, macOS, Linux and Termux (on the phone itself).
    python3 setup.py               # interactive
    python3 setup.py HOST:PORT     # connect to a wireless-debugging address directly
"""
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(os.path.expanduser("~"), ".config", "android-agent")
SERIAL_FILE = os.path.join(CONF, "serial")
TERMUX = "com.termux" in os.environ.get("PREFIX", "")
# ADB Keyboard (GPL-2.0, github.com/senzhk/ADBKeyBoard) - pinned release, checked by hash.
ADBKB_URL = "https://github.com/senzhk/ADBKeyBoard/releases/download/v2.5-dev/keyboardservice-debug.apk"
ADBKB_SHA256 = "41a8a0996d7397a2390d1ca16a75cb66c4a7bdaa89cf4e63600a4d3fb346fbbb"


def say(msg=""):
    print(msg, flush=True)


def ask(q, default="n"):
    try:
        a = input(f"{q} [{'Y/n' if default == 'y' else 'y/N'}] ").strip().lower()
    except EOFError:
        a = ""
    return (a or default) == "y"


def run(*cmd, timeout=60):
    r = subprocess.run(list(cmd), capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def ensure_adb():
    if shutil.which("adb"):
        return
    if TERMUX:
        say("adb not found. Installing android-tools...")
        subprocess.run(["pkg", "install", "-y", "android-tools"])
        if shutil.which("adb"):
            return
    say("adb (Android platform-tools) was not found.")
    sysname = platform.system()
    if sysname == "Windows":
        say("  Install: winget install Google.PlatformTools   (or download platform-tools from")
        say("  https://developer.android.com/tools/releases/platform-tools and add it to PATH)")
    elif sysname == "Darwin":
        say("  Install: brew install android-platform-tools")
    else:
        say("  Install: sudo apt install adb   (Fedora: sudo dnf install android-tools)")
    say("Then run this setup again.")
    sys.exit(1)


def devices():
    _, out = run("adb", "devices")
    rows = [l.split() for l in out.splitlines()[1:] if l.strip()]
    return [(r[0], r[1]) for r in rows if len(r) >= 2]


def explain_phone_side(wireless):
    say("\nOn the phone:")
    say("  1. Settings > About phone > tap 'Build number' 7 times (Xiaomi: 'OS version').")
    say("  2. Settings > Developer options > turn on 'USB debugging'.")
    say("     Xiaomi/Redmi/POCO: also 'USB debugging (Security settings)' (needed for taps)")
    say("     and 'Install via USB' (needed to install ADB Keyboard).")
    if wireless:
        say("  3. Turn on 'Wireless debugging' (phone on Wi-Fi). Android 11 or newer.")


def connect_wireless(addr=None):
    if not addr:
        explain_phone_side(wireless=True)
        if TERMUX:
            say("\n  Same phone? Put Termux and Settings in split screen so the pairing code stays visible.")
        say("\nFirst time only: Wireless debugging > 'Pair device with pairing code'.")
        pair = input("Pairing address shown there (IP:PORT, empty to skip): ").strip()
        if pair:
            code = input("Pairing code: ").strip()
            rc, out = run("adb", "pair", pair, code)
            say(out.strip())
        say("\nNow the address under 'IP address & Port' on the Wireless debugging screen.")
        if TERMUX:
            say("(On the same phone you can type 127.0.0.1:PORT)")
        addr = input("IP:PORT: ").strip()
        if TERMUX and addr.count(":") == 1 and not addr.startswith("127."):
            addr = "127.0.0.1:" + addr.split(":")[1]
    rc, out = run("adb", "connect", addr)
    say(out.strip())
    return addr


def choose_device(arg):
    if arg:
        return connect_wireless(arg)
    ready = [s for s, st in devices() if st == "device"]
    if ready:
        if len(ready) == 1:
            say(f"Found connected phone: {ready[0]}")
            return ready[0]
        for i, s in enumerate(ready):
            say(f"  [{i}] {s}")
        return ready[int(input("Which one? ") or 0)]
    unauthorized = [s for s, st in devices() if st == "unauthorized"]
    if unauthorized:
        say("The phone is connected but not authorized: unlock it and tap 'Allow' on the")
        say("'Allow USB debugging?' dialog (tick 'Always allow'), then run setup again.")
        sys.exit(1)
    if TERMUX:
        return connect_wireless()
    say("No phone found.")
    if ask("Connect with a USB cable? (easiest)", "y"):
        explain_phone_side(wireless=False)
        input("\nPlug the phone in, accept 'Allow USB debugging?' on it, then press Enter...")
        ready = [s for s, st in devices() if st == "device"]
        if ready:
            return ready[0]
        say("Still no phone. Check the cable (data cable, not charge-only) and the dialog on the phone.")
        sys.exit(1)
    return connect_wireless()


def install_adb_keyboard(serial):
    _, out = run("adb", "-s", serial, "shell", "pm list packages com.android.adbkeyboard")
    if "com.android.adbkeyboard" in out:
        say("ADB Keyboard: already installed.")
        return
    say("\nADB Keyboard lets the agent type non-English text (ç, é, ß, 中文, emoji).")
    say("It is switched on only while typing such text; your own keyboard is restored right after.")
    if not ask("Install ADB Keyboard (18 KB, open source)?", "y"):
        return
    tmp = os.path.join(tempfile.mkdtemp(), "adbkeyboard.apk")
    urllib.request.urlretrieve(ADBKB_URL, tmp)
    if hashlib.sha256(open(tmp, "rb").read()).hexdigest() != ADBKB_SHA256:
        say("Download did not match the expected checksum; not installing.")
        return
    say("Installing... if the phone asks, tap Install / Allow.")
    rc, out = run("adb", "-s", serial, "install", "-r", tmp, timeout=180)
    say(out.strip().splitlines()[-1] if out.strip() else "")
    if "USER_RESTRICTED" in out:
        say("Blocked by the phone. Xiaomi: turn on 'Install via USB' in Developer options and retry.")


def check_pillow():
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass
    say("\nOptional: Pillow makes fallback screenshots small (far fewer tokens).")
    if ask("Install Pillow now?", "y"):
        if TERMUX:
            subprocess.run(["pkg", "install", "-y", "python-pillow"])
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", "--user", "pillow"])


def main():
    say("android-agent setup\n")
    ensure_adb()
    serial = choose_device(sys.argv[1] if len(sys.argv) > 1 else None)
    rc, _ = run("adb", "-s", serial, "get-state")
    if rc != 0:
        say(f"Could not connect to {serial}.")
        sys.exit(1)
    os.makedirs(CONF, exist_ok=True)
    open(SERIAL_FILE, "w").write(serial)
    say(f"\nSaved device {serial} -> {SERIAL_FILE}")
    _, out = run("adb", "-s", serial, "shell", "input keyevent 0")
    if "INJECT_EVENTS" in out or "SecurityException" in out:
        say("Warning: the phone refuses taps. Xiaomi: turn on 'USB debugging (Security settings)'.")
    install_adb_keyboard(serial)
    check_pillow()
    say("\nFirst look at the screen:")
    subprocess.run([sys.executable, os.path.join(HERE, "phone.py"), "screen", "--full"])
    if shutil.which("claude") and ask("\nRegister the MCP server with Claude Code?", "y"):
        subprocess.run(["claude", "mcp", "add", "phone", "--", sys.executable,
                        os.path.join(HERE, "mcp_server.py")])
    say(f"\nDone. Try:  python3 {os.path.join(HERE, 'phone.py')} screen")


if __name__ == "__main__":
    main()
