#!/usr/bin/env python3
"""android-agent: give your phone a task in plain language; a model uses the phone tools to do it.

    python agent.py "turn on Bluetooth"
    python agent.py --provider openai --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \\
                    --model gemini-2.5-flash "how many unread notifications do I have?"

Providers:
  anthropic (default)  Claude via the official SDK (pip install anthropic). Key: ANTHROPIC_API_KEY.
  openai               Any OpenAI-compatible chat endpoint (Gemini, Groq, OpenRouter, Ollama, ...).
                       Key: OPENAI_API_KEY (or --api-key-env NAME). No extra package needed.
The agent asks you in the terminal before anything irreversible (it has an `ask_user` tool).
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_server  # noqa: E402  (tool definitions + execution)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))

SYSTEM = """You operate the user's Android phone through tools. Work in small steps:
read with `screen` (cheap text), act on one element, check the result. Prefer `tap_label`, `find`,
`wait_for`, `open_link` and recipes over long manual sequences. Use `ocr`, then `screenshot`, only
when the text list is empty.
Before anything irreversible or outward-facing (sending, posting, buying, deleting, installing,
changing account/security settings, granting permissions) call `ask_user` and wait for a yes.
When the task is done, reply with one or two plain sentences about the result.
"""

ASK_USER = {"name": "ask_user", "description": "Ask the user a question in the terminal (yes/no or short answer). "
            "Required before irreversible or outward-facing actions.",
            "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}},
                            "required": ["question"]}}


def skill_text():
    try:
        return open(os.path.join(HERE, "SKILL.md"), encoding="utf-8").read().split("---", 2)[-1]
    except OSError:
        return ""


def run_tool(name, args):
    """Execute a tool; returns (text, image_b64 or None, is_error)."""
    if name == "ask_user":
        print(f"\n? {args.get('question', '')}")
        try:
            return input("> ").strip() or "(no answer)", None, False
        except EOFError:
            return "(no answer: not interactive) - do not proceed with the irreversible step", None, False
    content, is_err = mcp_server.call(name, args)
    text = "\n".join(c["text"] for c in content if c["type"] == "text")
    image = next((c["data"] for c in content if c["type"] == "image"), None)
    return text, image, is_err


def log_step(name, args, text):
    short = json.dumps(args, ensure_ascii=False)
    print(f"· {name} {short[:80]}")
    first = text.strip().splitlines()[0] if text.strip() else ""
    if first:
        print(f"  {first[:110]}")


# ---------- Claude (official SDK) ----------
def run_anthropic(task, model, max_steps, effort):
    try:
        import anthropic
    except ImportError:
        sys.exit("Install the SDK first: pip install anthropic")
    client = anthropic.Anthropic()
    tools = [{"name": t["name"], "description": t["description"], "input_schema": t["inputSchema"]}
             for t in mcp_server.TOOLS + [ASK_USER]]
    messages = [{"role": "user", "content": task}]
    used_in = used_out = 0
    for _ in range(max_steps):
        response = client.beta.messages.create(
            model=model, max_tokens=16000, system=SYSTEM + skill_text(), tools=tools,
            messages=messages, output_config={"effort": effort},
            cache_control={"type": "ephemeral"},  # re-sent tools/system/history are cached
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        u = response.usage
        used_in += (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        used_out += u.output_tokens or 0
        if response.stop_reason == "refusal":
            print("The model declined this request.")
            break
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        messages.append({"role": "assistant", "content": response.content})
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            print("\n" + "".join(b.text for b in response.content if b.type == "text").strip())
            break
        results = []
        for c in calls:
            text, image, is_err = run_tool(c.name, c.input)
            log_step(c.name, c.input, text)
            content = [{"type": "text", "text": text or "ok"}]
            if image:
                content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}}]
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": content, "is_error": is_err})
        messages.append({"role": "user", "content": results})
    else:
        print(f"Stopped after {max_steps} steps.")
    print(f"[tokens: ~{used_in} in, ~{used_out} out]")


# ---------- any OpenAI-compatible endpoint ----------
def chat(base_url, key, payload):
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def run_openai(task, model, max_steps, base_url, key):
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["inputSchema"]}}
             for t in mcp_server.TOOLS + [ASK_USER] if t["name"] != "screenshot"]
    messages = [{"role": "system", "content": SYSTEM + skill_text()}, {"role": "user", "content": task}]
    used_in = used_out = 0
    for _ in range(max_steps):
        r = chat(base_url, key, {"model": model, "messages": messages, "tools": tools})
        u = r.get("usage") or {}
        used_in += u.get("prompt_tokens", 0)
        used_out += u.get("completion_tokens", 0)
        msg = r["choices"][0]["message"]
        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
        calls = msg.get("tool_calls") or []
        if not calls:
            print("\n" + (msg.get("content") or "").strip())
            break
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            text, image, is_err = run_tool(name, args)
            log_step(name, args, text)
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": (("ERROR: " if is_err else "") + (text or "ok"))})
    else:
        print(f"Stopped after {max_steps} steps.")
    print(f"[tokens: ~{used_in} in, ~{used_out} out]")


def main():
    p = argparse.ArgumentParser(description="Give your phone a task in plain language.")
    p.add_argument("task")
    p.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    p.add_argument("--model", help="default: claude-opus-5-5 (anthropic); required for openai")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"],
                   help="Claude effort level (default medium)")
    p.add_argument("--base-url", default="https://api.openai.com/v1", help="OpenAI-compatible endpoint")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", help="env var holding the key (openai provider)")
    p.add_argument("--max-steps", type=int, default=40)
    a = p.parse_args()
    if a.provider == "anthropic":
        run_anthropic(a.task, a.model or "claude-opus-5-5", a.max_steps, a.effort)
    else:
        if not a.model:
            sys.exit("--model is required with --provider openai")
        key = os.environ.get(a.api_key_env)
        if not key:
            sys.exit(f"Set {a.api_key_env} to your API key.")
        run_openai(a.task, a.model, a.max_steps, a.base_url, key)


if __name__ == "__main__":
    main()
