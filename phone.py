#!/usr/bin/env python3
"""phone-agent: let an AI agent use an Android phone and its apps, cheaply.

The screen is read as a short numbered text list (from the accessibility tree)
instead of screenshots, so each look costs ~100-400 tokens instead of ~1,500.

Commands:
  screen [--full]          numbered list of what is on screen (default: only what changed)
  tap N | X,Y              tap element N (from the last `screen`) or a coordinate
  longpress N | X,Y        long press
  type "text"              type into the focused field
  swipe up|down|left|right [N]   swipe the screen (or scrollable element N)
  key back|home|enter|recents|del|tab   send a key
  open PACKAGE|name        open an app (package name or part of its label/package)
  apps [filter]            list launchable apps
  shot                     save a small grayscale screenshot (when text is not enough)
  wait [sec]               wait until the screen settles
Chain commands with a lone comma:  phone.py tap 5 , wait , type hello , key enter
Device: set ANDROID_SERIAL (adb serial), e.g. 127.0.0.1:42861
Safety: tap/type refuse to act if another app came to the front since the last
`screen` (exit code 3). Set PA_FORCE=1 to override.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

STATE = os.path.expanduser("~/.cache/phone-agent/last.json")
REMOTE_XML = "/data/local/tmp/pa_ui.xml"
KEYS = {"back": 4, "home": 3, "enter": 66, "recents": 187, "del": 67, "tab": 61}


def adb(*args, timeout=30):
    r = subprocess.run(["adb", *args], capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def sh(cmd, timeout=30):
    out, err = adb("shell", cmd, timeout=timeout)
    return out + err


# ---------- seeing ----------
def dump_xml(tries=3):
    # uiautomator fails ("could not get idle state") while the screen is animating; retry.
    for _ in range(tries):
        res = sh(f"rm -f {REMOTE_XML}; uiautomator dump {REMOTE_XML} 2>&1")
        if "dumped to" in res:
            out, _ = adb("exec-out", "cat", REMOTE_XML)
            i = out.find("<?xml")
            if i >= 0:
                return out[i:]
        time.sleep(0.7)
    return ""


def parse_bounds(b):
    m = re.findall(r"\d+", b or "")
    return tuple(map(int, m)) if len(m) == 4 else None


def inside(child, parent):
    b = parent["b"]
    return b[0] <= child["x"] <= b[2] and b[1] <= child["y"] <= b[3]


def elements(xml):
    """Reduce the UI tree to a short list of meaningful elements."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], ""
    package, raw = "", []
    for n in root.iter("node"):
        a = n.attrib
        package = package or a.get("package", "")
        b = parse_bounds(a.get("bounds"))
        if not b or b[2] - b[0] < 4 or b[3] - b[1] < 4:
            continue
        text = (a.get("text") or "").strip()
        desc = (a.get("content-desc") or "").strip()
        clickable = a.get("clickable") == "true" or a.get("long-clickable") == "true"
        scrollable = a.get("scrollable") == "true"
        editable = a.get("class", "").endswith(("EditText", "AutoCompleteTextView"))
        checkable = a.get("checkable") == "true"
        if not (text or desc or clickable or scrollable or editable):
            continue
        kind = ("input" if editable else "list" if scrollable else
                ("toggle" if checkable else "button") if clickable else "text")
        label = text or desc
        if not label:
            rid = a.get("resource-id", "").split("/")[-1]
            label = f"#{rid}" if rid else ""
        if kind == "text" and not label:
            continue
        flags = []
        if checkable:
            flags.append("on" if a.get("checked") == "true" else "off")
        if editable and a.get("focused") == "true":
            flags.append("focused")
        if a.get("enabled") == "false":
            flags.append("disabled")
        cls = a.get("class", "").split(".")[-1]
        hint = "icon" if any(k.attrib.get("class", "").endswith(("ImageView", "ImageButton"))
                             for k in n.iter("node") if k is not n) or cls.endswith("ImageButton") else ""
        raw.append({"t": kind, "e": label[:60], "x": (b[0] + b[2]) // 2,
                    "y": (b[1] + b[3]) // 2, "b": b, "k": ",".join(flags), "h": hint})

    # Fold plain text into its innermost clickable parent to avoid duplicates.
    out = []
    for el in raw:
        if el["t"] == "text":
            parent = next((p for p in reversed(out)
                           if p["t"] in ("button", "toggle") and inside(el, p)), None)
            if parent:
                if parent["e"].startswith("#") or not parent["e"]:
                    parent["e"] = el["e"]
                elif el["e"] not in parent["e"] and len(parent["e"]) < 50:
                    parent["e"] = (parent["e"] + " · " + el["e"])[:60]
                continue
        out.append(el)

    # Last resort for unlabeled controls: describe them by shape and position.
    if out:
        W = max(e["b"][2] for e in out) or 1
        H = max(e["b"][3] for e in out) or 1
        for el in out:
            if not el["e"]:
                v = "top" if el["y"] < H / 3 else "bottom" if el["y"] > 2 * H / 3 else "middle"
                h = "left" if el["x"] < W / 3 else "right" if el["x"] > 2 * W / 3 else "center"
                el["e"] = f"? {el.get('h') or 'unlabeled'} {v}-{h}"
    for el in out:
        el.pop("h", None)
    return out, package


def line(i, el):
    flags = f" ({el['k']})" if el["k"] else ""
    return f"[{i}] {el['t']} \"{el['e']}\"{flags}"


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def screen(full=False):
    xml = dump_xml()
    if not xml:
        print("could not read the screen (locked or secure screen?) -> try `shot`")
        return
    items, package = elements(xml)
    prev = load_state()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"package": package, "items": items}, open(STATE, "w"), ensure_ascii=False)
    lines = [line(i, el) for i, el in enumerate(items)]
    if not full and prev.get("package") == package and prev.get("items"):
        seen = {line(i, el) for i, el in enumerate(prev["items"])}
        changed = [l for l in lines if l not in seen]
        if len(changed) < len(lines) * 0.6:
            print(f"{package} | {len(items)} items | {len(changed)} changed:" if changed
                  else f"{package} | no change")
            print("\n".join(changed))
            return
    print(f"{package} | {len(items)} items")
    print("\n".join(lines))
    if len(items) <= 2 and os.environ.get("PA_AUTOSHOT", "1") == "1":
        # Text tree is (nearly) empty: Flutter, games, some WebViews. Fall back to a small image.
        print("(very few items: Flutter/game/WebView?) small screenshot:")
        shot()


def target(arg):
    if re.fullmatch(r"\d+,\d+", arg):
        return tuple(map(int, arg.split(",")))
    el = load_state()["items"][int(arg)]
    return el["x"], el["y"]


# ---------- acting ----------
def foreground():
    out = sh("dumpsys window | grep -m1 mCurrentFocus")
    m = re.search(r"\{[^}]*\s(\S+)/", out)
    return m.group(1) if m else ""


def guard():
    """Refuse to act blind: the app we last looked at must still be in front."""
    if os.environ.get("PA_FORCE") == "1":
        return
    expected = load_state().get("package", "")
    current = foreground()
    if expected and current and current != expected:
        print(f"STOPPED: '{current}' is in front, last screen was '{expected}'. Run `screen` again.")
        sys.exit(3)


def tap(arg, long=False):
    guard()
    x, y = target(arg)
    sh(f"input swipe {x} {y} {x} {y} 700" if long else f"input tap {x} {y}")


def type_text(text, guarded=False):
    if not guarded:
        guard()
    if all(ord(c) < 128 for c in text):
        safe = text.replace("\\", "\\\\").replace("'", "'\\''").replace(" ", "%s")
        sh(f"input text '{safe}'")
        return
    # Non-ASCII: `input text` cannot type it. Use ADB Keyboard if it is the active IME.
    if "com.android.adbkeyboard" in sh("settings get secure default_input_method"):
        q = text.replace("'", "'\\''")
        sh(f"am broadcast -a ADB_INPUT_TEXT --es msg '{q}' >/dev/null")
        return
    print("warning: no ADB Keyboard for non-ASCII text; typing an ASCII approximation")
    table = str.maketrans("çğıöşüÇĞİÖŞÜâîûÂÎÛ", "cgiosuCGIOSUaiuAIU")
    type_text(text.translate(table), guarded=True)


def swipe(direction, n=None):
    if n is not None:
        b = load_state()["items"][int(n)]["b"]
    else:
        w, h = sh("wm size").split(":")[-1].strip().split("x")
        b = (0, 0, int(w), int(h))
    cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
    dx, dy = (b[2] - b[0]) * 3 // 10, (b[3] - b[1]) * 3 // 10
    # "up" moves content up (reveals what is below), like a finger swiping up.
    v = {"up": (cx, cy + dy, cx, cy - dy), "down": (cx, cy - dy, cx, cy + dy),
         "left": (cx + dx, cy, cx - dx, cy), "right": (cx - dx, cy, cx + dx, cy)}[direction]
    sh("input swipe %d %d %d %d 300" % v)


def apps(filt=""):
    out = sh("cmd package query-activities --brief -a android.intent.action.MAIN "
             "-c android.intent.category.LAUNCHER")
    pkgs = sorted({l.strip().split("/")[0] for l in out.splitlines() if "/" in l})
    return [p for p in pkgs if filt.lower() in p.lower()]


def open_app(name):
    pkg = name if "." in name else (apps(name) or [None])[0]
    if not pkg:
        print("app not found")
        return
    sh(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1")
    print("opened:", pkg)


def shot():
    png = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True).stdout
    path = os.path.expanduser("~/.cache/phone-agent/screen.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("L")
        im.thumbnail((360, 800))
        im.save(path)
    except Exception:
        open(path, "wb").write(png)
    print(path)


def wait(sec=1.0):
    """Wait until the focused window stops changing (at most 3*sec)."""
    last, t0 = None, time.time()
    time.sleep(0.4)
    while time.time() - t0 < sec * 3:
        h = hashlib.md5(sh("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'").encode()).hexdigest()
        if h == last:
            return
        last = h
        time.sleep(sec / 2)


def run(args):
    cmd, a = args[0], args[1:]
    if cmd == "screen": screen("--full" in a)
    elif cmd == "tap": tap(a[0])
    elif cmd == "longpress": tap(a[0], long=True)
    elif cmd == "type": type_text(" ".join(a))
    elif cmd == "swipe": swipe(a[0], a[1] if len(a) > 1 else None)
    elif cmd == "key": sh(f"input keyevent {KEYS.get(a[0], a[0])}")
    elif cmd == "open": open_app(" ".join(a))
    elif cmd == "apps": print("\n".join(apps(a[0] if a else "")))
    elif cmd == "shot": shot()
    elif cmd == "wait": wait(float(a[0]) if a else 1.0)
    else: print(__doc__)


if __name__ == "__main__":
    groups, cur = [], []
    for x in sys.argv[1:] or ["help"]:
        if x == ",":
            groups.append(cur)
            cur = []
        else:
            cur.append(x)
    groups.append(cur)
    for g in groups:
        if g:
            run(g)
