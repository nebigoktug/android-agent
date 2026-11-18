#!/usr/bin/env python3
"""android-agent: let an AI agent use an Android phone and its apps, cheaply.

The screen is read as a short numbered text list (from the accessibility tree)
instead of screenshots, so each look costs ~100-400 tokens instead of ~1,500.

Commands:
  screen [--full]          numbered list of what is on screen (default: only what changed)
  tap N | X,Y | "label"    tap element N (from the last `screen`), a coordinate, or by label
                           (label: case/accent-insensitive match on the live screen)
  find "label" [--down]    scroll until it is on screen (no agent turns per swipe)
  wait-for "label" [sec]   wait until it appears (default 15 s)
  notifications [N] [--all]  current notifications, newest first, without opening apps
  status                   battery, screen on/off, front app, keyboard, auto-rotate, network
  record NAME | stop       record the following steps as a recipe (taps saved by label)
  play NAME [key=value]    replay a recipe without the model; {key} in typed text is replaced
  recipes                  list saved recipes
  longpress N | X,Y        long press
  type "text"              type into the focused field
  swipe up|down|left|right [N]   swipe the screen (or scrollable element N)
  key back|home|enter|recents|del|tab   send a key
  open PACKAGE|name [--fresh]  open an app (--fresh: restart it from its home screen)
  apps [filter]            list launchable apps
  shot                     save a small grayscale screenshot (when text is not enough)
  ocr                      read text from the screen image (games, Flutter); `tap N` works on it
                           (needs tesseract; language via AA_OCR_LANG, e.g. eng+tur)
  wait [sec]               wait until the screen settles
  link URI                 open a deep link or URL (geo:, https://...) - often skips many taps
  lock | unlock            pin to portrait for a session / restore the user's rotation setting
Chain commands with a lone comma:  phone.py tap 5 , wait , type hello , key enter
Device: ANDROID_SERIAL, or the device saved by setup.sh (~/.config/android-agent/serial).
Safety: tap/type refuse to act if another app came to the front since the last
`screen` (exit code 3). Set AA_FORCE=1 to override.
"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ORIENTATION = "portrait"
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

STATE = os.path.expanduser("~/.cache/android-agent/last.json")
REMOTE_XML = "/data/local/tmp/aa_ui.xml"
KEYS = {"back": 4, "home": 3, "enter": 66, "recents": 187, "del": 67, "tab": 61}


SERIAL_FILE = os.path.expanduser("~/.config/android-agent/serial")
_checked = False


def ensure_device():
    """Use ANDROID_SERIAL, else the device saved by setup.sh; reconnect once if it dropped."""
    global _checked
    if _checked:
        return
    _checked = True
    if not os.environ.get("ANDROID_SERIAL") and os.path.exists(SERIAL_FILE):
        os.environ["ANDROID_SERIAL"] = open(SERIAL_FILE).read().strip()
    serial = os.environ.get("ANDROID_SERIAL", "")
    if ":" in serial:
        st = subprocess.run(["adb", "-s", serial, "get-state"], capture_output=True, timeout=10)
        if st.returncode != 0:
            subprocess.run(["adb", "connect", serial], capture_output=True, timeout=15)
            st = subprocess.run(["adb", "-s", serial, "get-state"], capture_output=True, timeout=10)
        if st.returncode != 0:
            # Wireless debugging picks a new port after a reboot or toggle: look it up via mDNS.
            found = discover_wireless()
            if found:
                subprocess.run(["adb", "connect", found], capture_output=True, timeout=15)
                os.environ["ANDROID_SERIAL"] = found
                try:
                    os.makedirs(os.path.dirname(SERIAL_FILE), exist_ok=True)
                    open(SERIAL_FILE, "w").write(found)
                except OSError:
                    pass


def discover_wireless():
    """Return HOST:PORT of a phone advertising wireless debugging (adb mDNS), or None."""
    try:
        out = subprocess.run(["adb", "mdns", "services"], capture_output=True, timeout=10).stdout.decode()
    except Exception:
        return None
    for l in out.splitlines():
        if "_adb-tls-connect" in l:
            m = re.search(r"(\d+\.\d+\.\d+\.\d+:\d+)", l)
            if m:
                return m.group(1)
    return None


def adb(*args, timeout=30):
    ensure_device()
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
    global ORIENTATION
    ORIENTATION = "landscape" if root.attrib.get("rotation") in ("1", "3") else "portrait"
    package, raw = "", []
    for n in root.iter("node"):
        a = n.attrib
        package = package or a.get("package", "")
        b = parse_bounds(a.get("bounds"))
        if not b or b[2] - b[0] < 4 or b[3] - b[1] < 4:
            continue
        text = " ".join((a.get("text") or "").split())
        desc = " ".join((a.get("content-desc") or "").split())
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

    # Switches without their own label take the label of the row they sit in.
    for el in out:
        if el["t"] == "toggle" and (not el["e"] or el["e"].startswith("#")):
            row = next((p for p in out if p is not el and p["t"] in ("button", "toggle") and inside(el, p)
                        and p["e"] and not p["e"].startswith("#")), None)
            if row and row["t"] == "toggle":
                el["drop"] = True  # the whole row is already the switch
            elif row:
                el["e"] = row["e"].split(" · ")[0]
    out = [el for el in out if not el.get("drop")]

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
            print(f"{package} | {ORIENTATION} | {len(items)} items | {len(changed)} changed:" if changed
                  else f"{package} | {ORIENTATION} | no change")
            print("\n".join(changed))
            return
    print(f"{package} | {ORIENTATION} | {len(items)} items")
    print("\n".join(lines))
    if len(items) <= 2 and os.environ.get("AA_AUTOSHOT", "1") == "1":
        # Text tree is (nearly) empty: Flutter, games, some WebViews. Fall back to a small image.
        import shutil
        if shutil.which("tesseract"):
            print("(very few items: Flutter/game/WebView?) reading the image as text:")
            ocr()
        else:
            print("(very few items: Flutter/game/WebView?) small screenshot:")
            shot()


# ---------- finding things by label ----------
_TR = str.maketrans({"İ": "i", "I": "ı", "ı": "i"})


def norm(t):
    """Case- and accent-insensitive form for matching labels (Turkish dotted/dotless i too)."""
    import unicodedata
    t = t.translate(_TR).casefold()
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def read_now():
    """Read the screen and save it as the current numbering. Returns (items, package)."""
    items, package = elements(dump_xml())
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"package": package, "items": items}, open(STATE, "w"), ensure_ascii=False)
    return items, package


def match(items, query):
    """Index of the element whose label best matches `query`, or None."""
    def compact(t):  # "Wi-Fi" == "wifi"
        return re.sub(r"[\W_]+", "", t)

    q = compact(norm(query))
    best, best_score = None, 0.0
    for i, el in enumerate(items):
        lab = compact(norm(el["e"]))
        if not lab or el["e"].startswith("?"):
            continue
        parts = [compact(norm(p)) for p in el["e"].split(" · ")]
        if lab == q or q in parts:
            score = 3.0
        elif lab.startswith(q):
            score = 2.0
        elif q in lab:
            score = 1.0
        else:
            continue
        if el["t"] in ("button", "toggle", "input"):
            score += 0.5
        score -= len(lab) / 1000  # prefer the shorter, more specific label
        if score > best_score:
            best, best_score = i, score
    return best


def describe(items, i):
    """Line for item i, plus the on/off state of a switch in the same row, if any."""
    el = items[i]
    extra = ""
    if el["t"] != "toggle":
        top, bottom = el["b"][1], el["b"][3]
        for o in items:
            if o is not el and o["t"] == "toggle" and top <= o["y"] <= bottom:
                extra = f"  <- switch {o['k']}"
                break
    return line(i, el) + extra


def is_label(arg):
    return not re.fullmatch(r"\d+(,\d+)?", arg)


def target(arg):
    """Resolve a tap target. For element numbers, re-read the screen and make sure the same
    element (kind + label) is still there; use its current position, or stop."""
    if re.fullmatch(r"\d+,\d+", arg):
        return tuple(map(int, arg.split(",")))
    if is_label(arg):  # tap "Save": find it on the screen as it is right now
        items, package = read_now()
        i = match(items, arg)
        if i is None:
            print(f"STOPPED: nothing matching \"{arg}\" on screen ({package}). Try `find` or `screen`.")
            sys.exit(5)
        print(f"{package} | tapped {line(i, items[i])}")
        return items[i]["x"], items[i]["y"]
    state = load_state()
    el = state["items"][int(arg)]
    if os.environ.get("AA_VERIFY", "1") != "1":
        return el["x"], el["y"]
    items, package = elements(dump_xml())
    same = [e for e in items if e["t"] == el["t"] and e["e"] == el["e"]]
    if not same:
        print(f"STOPPED: element [{arg}] {el['t']} \"{el['e']}\" is no longer on screen. Run `screen` again.")
        sys.exit(4)
    best = min(same, key=lambda e: abs(e["x"] - el["x"]) + abs(e["y"] - el["y"]))
    # keep numbering stable for chained commands: only positions are refreshed
    el["x"], el["y"], el["b"] = best["x"], best["y"], best["b"]
    json.dump(state, open(STATE, "w"), ensure_ascii=False)
    return el["x"], el["y"]


# ---------- acting ----------
def foreground():
    out = sh("dumpsys window | grep -m1 mCurrentFocus")
    m = re.search(r"\{[^}]*\s(\S+)/", out)
    if m:
        return m.group(1)
    # System windows have no package/activity, e.g. "NotificationShade", "StatusBar".
    m = re.search(r"\{\S+ u\d+ ([^}\s]+)\}", out)
    return f"system:{m.group(1)}" if m else ""


def guard():
    """Refuse to act blind: the app we last looked at must still be in front."""
    if os.environ.get("AA_FORCE") == "1":
        return
    expected = load_state().get("package", "")
    current = foreground()
    if expected and current and current != expected:
        print(f"STOPPED: '{current}' is in front, last screen was '{expected}'. Run `screen` again.")
        sys.exit(3)


def tap(arg, long=False):
    if not is_label(arg):  # label taps read the live screen themselves
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
    # Non-ASCII: `input text` cannot type it. Switch to ADB Keyboard only for this text,
    # then give the user's own keyboard back.
    if "com.android.adbkeyboard" not in sh("pm list packages com.android.adbkeyboard"):
        print("warning: ADB Keyboard not installed; typing an ASCII approximation")
        table = str.maketrans("çğıöşüÇĞİÖŞÜâîûÂÎÛ", "cgiosuCGIOSUaiuAIU")
        type_text(text.translate(table), guarded=True)
        return
    ime = "com.android.adbkeyboard/.AdbIME"
    previous = sh("settings get secure default_input_method").strip()
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    try:
        sh(f"ime enable {ime} >/dev/null; ime set {ime} >/dev/null")
        time.sleep(0.4)
        sh(f"am broadcast -a ADB_INPUT_B64 --es msg {b64} >/dev/null")
        time.sleep(0.3)
    finally:
        if previous and previous != ime and "/" in previous:
            sh(f"ime set {previous} >/dev/null")
        sh(f"ime disable {ime} >/dev/null")


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


ROT_FILE = os.path.expanduser("~/.cache/android-agent/rotation.json")


def lock_portrait():
    """Pin the screen to portrait for an agent session; remembers the user's setting."""
    acc = sh("settings get system accelerometer_rotation").strip()
    rot = sh("settings get system user_rotation").strip()
    if not os.path.exists(ROT_FILE):
        json.dump({"accelerometer_rotation": acc, "user_rotation": rot}, open(ROT_FILE, "w"))
    sh("settings put system accelerometer_rotation 0; settings put system user_rotation 0")
    print(f"portrait locked (saved: auto-rotate={acc}, rotation={rot}); run `unlock` to restore")


def unlock_rotation():
    if not os.path.exists(ROT_FILE):
        print("nothing to restore")
        return
    old = json.load(open(ROT_FILE))
    for k, v in old.items():
        if re.fullmatch(r"\d+", v or ""):
            sh(f"settings put system {k} {v}")
    os.remove(ROT_FILE)
    print(f"restored: {old}")


def link(uri):
    """Open a deep link / URL (often skips several taps), e.g.
    geo:0,0?q=Clock+Tower+Izmir   https://www.youtube.com/results?search_query=lofi"""
    q = uri.replace("'", "'\\''")
    out = sh(f"am start -W -a android.intent.action.VIEW -d '{q}' 2>&1")
    print("opened" if "Error" not in out else out.strip())


def apps(filt=""):
    out = sh("cmd package query-activities --brief -a android.intent.action.MAIN "
             "-c android.intent.category.LAUNCHER")
    pkgs = sorted({l.strip().split("/")[0] for l in out.splitlines() if "/" in l})
    return [p for p in pkgs if filt.lower() in p.lower()]


def open_app(name, fresh=False):
    if "." in name:
        pkg = name
    else:  # best match: package ending in ".name", else the shortest package containing it
        found = apps(name)
        exact = [p for p in found if p.lower().endswith("." + name.lower())]
        pkg = (exact or sorted(found, key=len) or [None])[0]
    if not pkg:
        print("app not found")
        return
    if fresh:  # start from the app's home screen instead of where it was left
        sh(f"am force-stop {pkg}")
    sh(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1")
    print("opened:", pkg)


def shot():
    ensure_device()  # binary output: call adb directly, not through the text helper
    png = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True, timeout=30).stdout
    path = os.path.expanduser("~/.cache/android-agent/screen.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("L")
        im.thumbnail((360, 800))
        im.save(path)
    except Exception:
        open(path, "wb").write(png)
    print(path)


def find(query, max_swipes=8, direction="up"):
    """Scroll until an element matching `query` is on screen; print it. No agent turns needed."""
    last_sig = None
    for n in range(max_swipes + 1):
        items, package = read_now()
        i = match(items, query)
        if i is not None:
            print(f"{package} | found after {n} swipe(s): {describe(items, i)}")
            return i
        sig = tuple(el["e"] for el in items)
        if sig == last_sig:
            break  # the list did not move: reached the end
        last_sig = sig
        swipe(direction)
        time.sleep(0.6)
    print(f"not found: \"{query}\" (after {n} swipe(s))")
    sys.exit(5)


def wait_for(query, timeout=15.0):
    """Wait until something matching `query` appears (loading screens, sent confirmations...)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        items, package = read_now()
        i = match(items, query)
        if i is not None:
            print(f"{package} | appeared after {time.time() - t0:.1f}s: {describe(items, i)}")
            return i
        time.sleep(0.8)
    print(f"timeout: \"{query}\" did not appear in {timeout:.0f}s")
    sys.exit(6)


def _extra(block, name):
    m = re.search(rf"{re.escape(name)}=(?:String|SpannableString)?\s*\((.*?)\)\s*$", block, re.M)
    if m:
        return " ".join(m.group(1).split())
    return ""


def notifications(limit=15, include_ongoing=False):
    """Current notifications as short text lines, newest first. Read without opening any app."""
    out = sh("dumpsys notification --noredact", timeout=40)
    head = out.split("Archive")[0]  # current list only, not the history archive
    seen, rows = set(), []
    for block in head.split("NotificationRecord(")[1:]:
        key = re.search(r"key=(\S+)", block)
        key = key.group(1) if key else block[:40]
        if key in seen:
            continue
        seen.add(key)
        pkg = re.search(r"pkg=(\S+)", block)
        pkg = pkg.group(1) if pkg else "?"
        flags = re.search(r"flags=0x([0-9a-fA-F]+)", block)
        flags = int(flags.group(1), 16) if flags else 0
        if "::SUMMARY::" in block or (flags & 0x200):  # group summary
            continue
        if not include_ongoing and flags & 0x2:  # ongoing: music player, downloads, VPN...
            continue
        title = _extra(block, "android.title")
        text = _extra(block, "android.bigText") or _extra(block, "android.text")
        if not (title or text):
            continue
        when = re.search(r"when=(\d{10,})", block)
        when = int(when.group(1)) // 1000 if when else 0
        rows.append((when, pkg, title, text))
    rows.sort(reverse=True)
    if not rows:
        print("no notifications")
    for when, pkg, title, text in rows[:limit]:
        t = time.strftime("%d.%m %H:%M", time.localtime(when)) if when else "--"
        app = pkg.split(".")[-1]
        print(f"{t} {app}: {title[:60]}" + (f" — {text[:120]}" if text else ""))


def status():
    """One line about the phone: battery, screen, front app, keyboard, rotation, network."""
    bat = sh("dumpsys battery")
    lvl = re.search(r"level: (\d+)", bat)
    charging = re.search(r"(AC|USB|Wireless) powered: true", bat)
    pw = sh("dumpsys power | grep -m1 mWakefulness")
    awake = "Awake" in pw
    ime = sh("dumpsys input_method | grep -m1 -E 'mInputShown|mIsInputViewShown'")
    kb = "true" in ime
    wifi_st = sh("cmd wifi status 2>/dev/null | head -8").lower()
    wifi = "connected to" in wifi_st and "not connected" not in wifi_st
    rot = sh("settings get system accelerometer_rotation").strip()
    print(f"battery {lvl.group(1) if lvl else '?'}%{' charging' if charging else ''} | "
          f"screen {'on' if awake else 'off'} | front {foreground() or '?'} | "
          f"keyboard {'shown' if kb else 'hidden'} | auto-rotate {'on' if rot == '1' else 'off'} | "
          f"network {'wifi' if wifi else 'mobile/none'}")


def ocr():
    """Read text from the screen image (for games, Flutter apps, canvases) with Tesseract.
    Prints a numbered list like `screen`; `tap N` then taps the text's position."""
    import shutil
    import tempfile
    if not shutil.which("tesseract"):
        print("tesseract not installed (apt/brew/pkg install tesseract) -> falling back to `shot`")
        shot()
        return
    ensure_device()
    png = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True, timeout=30).stdout
    img = os.path.join(tempfile.mkdtemp(), "s.png")
    open(img, "wb").write(png)
    lang = os.environ.get("AA_OCR_LANG", "eng")
    r = subprocess.run(["tesseract", img, "stdout", "-l", lang, "--psm", "11", "tsv"],
                       capture_output=True, timeout=120)
    lines = {}
    for row in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        try:
            conf = float(f[10])
        except ValueError:
            continue
        if conf < 55:
            continue
        key = (f[2], f[3], f[4])  # block, paragraph, line
        x, y, w, h = map(int, f[6:10])
        ln = lines.setdefault(key, {"words": [], "b": [x, y, x + w, y + h]})
        ln["words"].append(f[11])
        b = ln["b"]
        b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)
    items = []
    for ln in sorted(lines.values(), key=lambda l: (l["b"][1] // 20, l["b"][0])):
        b = ln["b"]
        items.append({"t": "ocr", "e": " ".join(ln["words"])[:60], "x": (b[0] + b[2]) // 2,
                      "y": (b[1] + b[3]) // 2, "b": tuple(b), "k": ""})
    package = foreground()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"package": package, "items": items}, open(STATE, "w"), ensure_ascii=False)
    print(f"{package} | ocr ({lang}) | {len(items)} text lines")
    for i, el in enumerate(items):
        print(line(i, el))


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


# ---------- recipes: record a task once, replay it without the model ----------
RECIPES = os.path.expanduser("~/.config/android-agent/recipes")
RECORDING = os.path.expanduser("~/.cache/android-agent/recording")
RECORDABLE = {"tap", "longpress", "type", "swipe", "key", "open", "link", "find", "wait-for", "wait"}


def recording():
    try:
        return open(RECORDING).read().strip()
    except OSError:
        return ""


def record_prepare(args):
    """Step to store for the recipe being recorded (or None). Numbered taps become labels."""
    name = recording()
    if not name or not args or args[0] not in RECORDABLE:
        return None
    step = list(args)
    if step[0] in ("tap", "longpress") and len(step) > 1 and re.fullmatch(r"\d+", step[1]):
        items = load_state().get("items", [])
        i = int(step[1])
        if i < len(items) and items[i]["e"] and not items[i]["e"].startswith(("?", "#")):
            step[1] = items[i]["e"].split(" · ")[0]
        elif i < len(items):
            step[1] = f"{items[i]['x']},{items[i]['y']}"
    return step


def record_save(step):
    """Called only after the step succeeded."""
    name = recording()
    if not step or not name:
        return
    path = os.path.join(RECIPES, name + ".json")
    steps = json.load(open(path)) if os.path.exists(path) else []
    steps.append(step)
    json.dump(steps, open(path, "w"), ensure_ascii=False, indent=1)


def record_start(name):
    os.makedirs(RECIPES, exist_ok=True)
    os.makedirs(os.path.dirname(RECORDING), exist_ok=True)
    json.dump([], open(os.path.join(RECIPES, name + ".json"), "w"))
    open(RECORDING, "w").write(name)
    print(f"recording '{name}': run the steps, then `stop`. Use {{name}} in `type` for a parameter.")


def record_stop():
    name = recording()
    if not name:
        print("not recording")
        return
    os.remove(RECORDING)
    steps = json.load(open(os.path.join(RECIPES, name + ".json")))
    print(f"saved '{name}' ({len(steps)} steps):")
    for st in steps:
        print("  " + " ".join(st))


def play(name, params):
    path = os.path.join(RECIPES, name + ".json")
    if not os.path.exists(path):
        print(f"no recipe '{name}'. `recipes` lists them.")
        sys.exit(2)
    for st in json.load(open(path)):
        st = [re.sub(r"\{(\w+)\}", lambda m: params.get(m.group(1), m.group(0)), x) for x in st]
        print("> " + " ".join(st))
        run(st)
    print(f"done: {name}")


def list_recipes():
    names = sorted(f[:-5] for f in os.listdir(RECIPES) if f.endswith(".json")) if os.path.isdir(RECIPES) else []
    for n in names:
        steps = json.load(open(os.path.join(RECIPES, n + ".json")))
        params = sorted(set(re.findall(r"\{(\w+)\}", json.dumps(steps))))
        print(f"{n} ({len(steps)} steps)" + (f" params: {', '.join(params)}" if params else ""))
    if not names:
        print("no recipes yet: `record NAME` ... `stop`")


def run(args):
    cmd, a = args[0], args[1:]
    if cmd == "screen": screen("--full" in a)
    elif cmd == "tap": tap(a[0])
    elif cmd == "longpress": tap(a[0], long=True)
    elif cmd == "type":
        txt = " ".join(a)
        if recording() and re.fullmatch(r"\{\w+\}", txt):
            print(f"(recorded parameter {txt}; nothing typed now)")
        else:
            type_text(txt)
    elif cmd == "swipe": swipe(a[0], a[1] if len(a) > 1 else None)
    elif cmd == "key": sh(f"input keyevent {KEYS.get(a[0], a[0])}")
    elif cmd == "open": open_app(" ".join(x for x in a if x != "--fresh"), fresh="--fresh" in a)
    elif cmd == "apps": print("\n".join(apps(a[0] if a else "")))
    elif cmd == "shot": shot()
    elif cmd == "ocr": ocr()
    elif cmd == "lock": lock_portrait()
    elif cmd == "unlock": unlock_rotation()
    elif cmd == "link": link(" ".join(a))
    elif cmd == "wait": wait(float(a[0]) if a else 1.0)
    elif cmd == "notifications": notifications(int(a[0]) if a and a[0].isdigit() else 15,
                                               include_ongoing="--all" in a)
    elif cmd == "status": status()
    elif cmd == "record": record_start(a[0])
    elif cmd == "stop": record_stop()
    elif cmd == "play": play(a[0], dict(x.split("=", 1) for x in a[1:] if "=" in x))
    elif cmd == "recipes": list_recipes()
    elif cmd == "find": find(" ".join(x for x in a if x not in ("--down",)),
                             direction="down" if "--down" in a else "up")
    elif cmd == "wait-for": wait_for(a[0], float(a[1]) if len(a) > 1 else 15.0)
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
            step = record_prepare(g)
            run(g)
            record_save(step)
