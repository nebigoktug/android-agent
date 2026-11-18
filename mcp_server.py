#!/usr/bin/env python3
"""android-agent MCP server (stdio, no dependencies).

Exposes phone.py as MCP tools so any MCP client (Claude Code, Cursor, ...) can use the phone.
Register with Claude Code:
  claude mcp add phone -e ANDROID_SERIAL=127.0.0.1:PORT -- python3 /path/to/mcp_server.py
"""
import base64
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phone  # noqa: E402

PROTOCOL = "2025-06-18"
try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TOOLS = [
    {"name": "screen", "description": "Read the current screen as a short numbered text list "
     "(cheap: ~100-400 tokens). By default only changed items are returned; set full=true for all. "
     "Element numbers are used by tap/longpress/swipe.",
     "inputSchema": {"type": "object", "properties": {"full": {"type": "boolean"}}}},
    {"name": "tap", "description": "Tap element N from the last `screen`, or a coordinate 'X,Y'. "
     "Refuses if another app came to the front since the last screen read.",
     "inputSchema": {"type": "object", "properties": {"target": {"type": "string"},
                     "long": {"type": "boolean"}}, "required": ["target"]}},
    {"name": "type", "description": "Type text into the focused field.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "swipe", "description": "Swipe up/down/left/right on the screen or on scrollable element N. "
     "'up' reveals content below.",
     "inputSchema": {"type": "object", "properties": {
         "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
         "element": {"type": "integer"}}, "required": ["direction"]}},
    {"name": "key", "description": "Press a key: back, home, enter, recents, del, tab (or an Android keycode).",
     "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}},
    {"name": "open_app", "description": "Open an app by package name or part of it (e.g. 'youtube'). "
     "fresh=true restarts it from its home screen (loses its current state).",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "fresh": {"type": "boolean"}},
                     "required": ["name"]}},
    {"name": "open_link", "description": "Open a deep link or URL; often replaces many taps. Examples: "
     "'geo:0,0?q=Eiffel+Tower' (maps search), 'https://www.youtube.com/results?search_query=lofi', "
     "'tel:123' (dialer, does not call), 'mailto:a@b.c' (draft only).",
     "inputSchema": {"type": "object", "properties": {"uri": {"type": "string"}}, "required": ["uri"]}},
    {"name": "rotation_lock", "description": "lock=true pins the screen to portrait for the session and "
     "remembers the user's setting; lock=false restores it. Restore before finishing.",
     "inputSchema": {"type": "object", "properties": {"lock": {"type": "boolean"}}, "required": ["lock"]}},
    {"name": "tap_label", "description": "Tap the element whose label best matches `label` on the live "
     "screen (case/accent-insensitive). No `screen` call needed first.",
     "inputSchema": {"type": "object", "properties": {"label": {"type": "string"}, "long": {"type": "boolean"}},
                     "required": ["label"]}},
    {"name": "find", "description": "Scroll until an element matching `label` is visible and return it "
     "(with the state of a switch in its row). Cheaper than swipe+screen loops.",
     "inputSchema": {"type": "object", "properties": {"label": {"type": "string"},
                     "direction": {"type": "string", "enum": ["up", "down"]}}, "required": ["label"]}},
    {"name": "wait_for", "description": "Wait until an element matching `label` appears (default 15 s).",
     "inputSchema": {"type": "object", "properties": {"label": {"type": "string"}, "seconds": {"type": "number"}},
                     "required": ["label"]}},
    {"name": "notifications", "description": "Current notifications (newest first) without opening apps. "
     "Content is private: use it only for the user's task.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"},
                     "include_ongoing": {"type": "boolean"}}}},
    {"name": "status", "description": "One line: battery, screen on/off, front app, keyboard, auto-rotate, network.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "record_start", "description": "Start recording the following actions as a named recipe "
     "(taps are saved by label). Use type text '{name}' to make a parameter.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "record_stop", "description": "Stop recording and save the recipe.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "play_recipe", "description": "Replay a saved recipe without the model (zero tokens per step). "
     "params fills {placeholders}, e.g. {\"q\": \"lofi\"}.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"},
                     "params": {"type": "object"}}, "required": ["name"]}},
    {"name": "list_recipes", "description": "List saved recipes and their parameters.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_apps", "description": "List launchable app packages, optionally filtered.",
     "inputSchema": {"type": "object", "properties": {"filter": {"type": "string"}}}},
    {"name": "wait", "description": "Wait until the screen settles (seconds, default 1).",
     "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}}},
    {"name": "ocr", "description": "Read visible text from the screen image (for games/Flutter apps where "
     "`screen` is empty). Returns numbered lines you can `tap`. Needs Tesseract on the computer.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "screenshot", "description": "Small grayscale screenshot. Use only when the text list "
     "is not enough (images, maps, games, Flutter apps): it costs far more tokens.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def as_cli(name, a):
    """The CLI form of an action, so recipes recorded over MCP replay from the CLI too."""
    m = {"tap": lambda: ["longpress" if a.get("long") else "tap", str(a["target"])],
         "tap_label": lambda: ["longpress" if a.get("long") else "tap", str(a["label"])],
         "type": lambda: ["type", a["text"]], "key": lambda: ["key", a["key"]],
         "swipe": lambda: ["swipe", a["direction"]] + ([str(a["element"])] if a.get("element") is not None else []),
         "open_app": lambda: ["open", a["name"]] + (["--fresh"] if a.get("fresh") else []),
         "open_link": lambda: ["link", a["uri"]], "find": lambda: ["find", a["label"]],
         "wait_for": lambda: ["wait-for", a["label"]], "wait": lambda: ["wait", str(a.get("seconds", 1))]}
    return m[name]() if name in m else None


def call(name, a):
    buf = io.StringIO()
    step = phone.record_prepare(as_cli(name, a) or [])
    image = None
    try:
        with contextlib.redirect_stdout(buf):
            if name == "screen":
                os.environ["AA_AUTOSHOT"] = "0"
                phone.screen(bool(a.get("full")))
            elif name == "tap":
                phone.tap(str(a["target"]), long=bool(a.get("long")))
                print("ok")
            elif name == "type":
                if phone.recording() and __import__("re").fullmatch(r"\{\w+\}", a["text"]):
                    print(f"(recorded parameter {a['text']}; nothing typed now)")
                else:
                    phone.type_text(a["text"])
                    print("ok")
            elif name == "swipe":
                phone.swipe(a["direction"], a.get("element"))
                print("ok")
            elif name == "key":
                phone.sh(f"input keyevent {phone.KEYS.get(a['key'], a['key'])}")
                print("ok")
            elif name == "open_app":
                phone.open_app(a["name"], fresh=bool(a.get("fresh")))
            elif name == "open_link":
                phone.link(a["uri"])
            elif name == "rotation_lock":
                phone.lock_portrait() if a.get("lock") else phone.unlock_rotation()
            elif name == "tap_label":
                phone.tap(str(a["label"]), long=bool(a.get("long")))
            elif name == "find":
                phone.find(a["label"], direction=a.get("direction", "up"))
            elif name == "wait_for":
                phone.wait_for(a["label"], float(a.get("seconds", 15)))
            elif name == "notifications":
                phone.notifications(int(a.get("limit", 15)), bool(a.get("include_ongoing")))
            elif name == "status":
                phone.status()
            elif name == "record_start":
                phone.record_start(a["name"])
            elif name == "record_stop":
                phone.record_stop()
            elif name == "play_recipe":
                phone.play(a["name"], {k: str(v) for k, v in (a.get("params") or {}).items()})
            elif name == "list_recipes":
                phone.list_recipes()
            elif name == "list_apps":
                print("\n".join(phone.apps(a.get("filter", ""))))
            elif name == "wait":
                phone.wait(float(a.get("seconds", 1)))
                print("ok")
            elif name == "ocr":
                phone.ocr()
            elif name == "screenshot":
                phone.shot()
                path = os.path.expanduser("~/.cache/android-agent/screen.png")
                image = base64.b64encode(open(path, "rb").read()).decode()
            else:
                return [{"type": "text", "text": f"unknown tool {name}"}], True
    except SystemExit:
        return [{"type": "text", "text": buf.getvalue().strip()}], True
    except Exception as e:  # report, don't crash the server
        return [{"type": "text", "text": f"{buf.getvalue()}error: {e}"}], True
    phone.record_save(step)
    if image:
        return [{"type": "image", "data": image, "mimeType": "image/png"}], False
    text = buf.getvalue().strip()
    if name == "screen" and "very few items" in text:
        text += "\n(hint: call `screenshot`)"
    return [{"type": "text", "text": text or "ok"}], False


def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    msg["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        try:
            req = json.loads(raw)
        except ValueError:
            continue
        method, id_ = req.get("method"), req.get("id")
        if id_ is None:  # notification
            continue
        if method == "initialize":
            reply(id_, {"protocolVersion": req.get("params", {}).get("protocolVersion", PROTOCOL),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "android-agent", "version": "0.3.0"}})
        elif method == "tools/list":
            reply(id_, {"tools": TOOLS})
        elif method == "tools/call":
            p = req.get("params", {})
            content, is_err = call(p.get("name"), p.get("arguments") or {})
            reply(id_, {"content": content, "isError": is_err})
        elif method == "ping":
            reply(id_, {})
        else:
            reply(id_, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
