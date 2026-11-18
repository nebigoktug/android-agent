# phone-agent

Let an AI agent use your Android phone and its apps — cheaply, and without a PC.

Most phone agents look at the screen through screenshots (~1,500 tokens per look).
phone-agent reads the screen as a short numbered text list from Android's accessibility
tree instead, and only sends what changed:

```
com.android.settings | 15 items
[0] button "Search settings"
[5] button "Wi-Fi · HomeNetwork_5G"
[6] button "Bluetooth · On"
[9] button "Hotspot · Off"
...
```

That screen costs ~150 tokens. The agent then says `tap 5`.
A small grayscale screenshot is used only when the text is not enough (games, Flutter apps, maps).

> Status: early (v0.1). Works on a Xiaomi with Android 16 over wireless debugging.
> Token benchmark against other tools: coming soon.

## Why another one?

| | phone-agent | typical phone agents |
|---|---|---|
| Runs on the phone itself (Termux), no PC | yes | no (adb from a computer) |
| Default way of seeing | text list + diff | screenshots |
| Blind-tap guard (another app came to the front) | yes | — |
| Dependencies | Python + adb | varies |

## Setup

Quick way: `sh setup.sh` (installs adb in Termux if needed, pairs, connects, remembers the device
in `~/.config/phone-agent/serial`, and can register the MCP server with Claude Code).
After that, `phone.py` reconnects by itself when the wireless connection drops.

**Manual, on the phone itself (Termux):**

1. Developer options → turn on *USB debugging* and *Wireless debugging*
   (Xiaomi: also *USB debugging (Security settings)*, needed for taps).
2. Install adb (`pkg install android-tools`, or adb inside proot-distro).
3. Pair once: Wireless debugging → *Pair device with pairing code*, then
   `adb pair 127.0.0.1:PAIR_PORT CODE` (use split screen so the code stays visible).
4. Connect: `adb connect 127.0.0.1:PORT` (the port shown on the Wireless debugging screen).
5. `export ANDROID_SERIAL=127.0.0.1:PORT`

**From a computer:** plain `adb` over USB or Wi-Fi works the same way.

## Use

```sh
python3 phone.py screen            # what is on screen (only changes after the first call)
python3 phone.py screen --full
python3 phone.py tap 5
python3 phone.py type hello , key enter      # chain with a lone comma
python3 phone.py swipe up
python3 phone.py open youtube
python3 phone.py shot              # small screenshot, only when needed
```

### As an MCP server (Claude Code, Cursor, ...)

```sh
claude mcp add phone -- python3 /path/to/mcp_server.py   # uses the device saved by setup.sh
```

Tools: `screen`, `tap`, `type`, `swipe`, `key`, `open_app`, `list_apps`, `wait`, `screenshot`.

## Safety

- `tap`/`type` refuse to act if a different app is in front than the one last read
  (the user may have switched apps). Read the screen again, then act.
- Agents should ask the user before anything irreversible: sending messages, payments,
  deleting, changing account settings. See `SKILL.md`.
- Apps that block screenshots (banking etc.) show as black/empty — that is intended.

## Known limits

- Non-ASCII text needs [ADB Keyboard](https://github.com/senzhk/ADBKeyBoard) as the active keyboard;
  otherwise it is typed as an ASCII approximation.
- `uiautomator dump` takes ~1–3 s and can fail while the screen animates (retried automatically).
- Some apps expose unlabeled buttons; they show as `? icon bottom-left` etc.

## License

MIT
