#!/usr/bin/env python3
"""phone-agent MCP server (stdio, no dependencies).

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
    {"name": "list_apps", "description": "List launchable app packages, optionally filtered.",
     "inputSchema": {"type": "object", "properties": {"filter": {"type": "string"}}}},
    {"name": "wait", "description": "Wait until the screen settles (seconds, default 1).",
     "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}}},
    {"name": "screenshot", "description": "Small grayscale screenshot. Use only when the text list "
     "is not enough (images, maps, games, Flutter apps): it costs far more tokens.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def call(name, a):
    buf = io.StringIO()
    image = None
    try:
        with contextlib.redirect_stdout(buf):
            if name == "screen":
                os.environ["PA_AUTOSHOT"] = "0"
                phone.screen(bool(a.get("full")))
            elif name == "tap":
                phone.tap(str(a["target"]), long=bool(a.get("long")))
                print("ok")
            elif name == "type":
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
            elif name == "list_apps":
                print("\n".join(phone.apps(a.get("filter", ""))))
            elif name == "wait":
                phone.wait(float(a.get("seconds", 1)))
                print("ok")
            elif name == "screenshot":
                phone.shot()
                path = os.path.expanduser("~/.cache/phone-agent/screen.png")
                image = base64.b64encode(open(path, "rb").read()).decode()
            else:
                return [{"type": "text", "text": f"unknown tool {name}"}], True
    except SystemExit:
        return [{"type": "text", "text": buf.getvalue().strip()}], True
    except Exception as e:  # report, don't crash the server
        return [{"type": "text", "text": f"{buf.getvalue()}error: {e}"}], True
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
                        "serverInfo": {"name": "phone-agent", "version": "0.1.0"}})
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
