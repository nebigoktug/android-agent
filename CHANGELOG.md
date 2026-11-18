# Changelog

## 0.2.0
- Cross-platform `setup.py` (Windows, macOS, Linux, Termux; USB or wireless); replaces `setup.sh`
- Reconnects by itself when the wireless port changes (mDNS lookup)
- UTF-8 output on every OS (Windows consoles)
- Unicode typing through ADB Keyboard, switched on only while typing
- Device-free unit tests and CI on Windows, macOS and Linux

## 0.1.1
- Re-read and verify the target before every tap; stop if it moved or disappeared
- `open --fresh`, orientation in the screen header, better app-name matching
- Notification shade counts as a different foreground (blind-tap guard)
- Deep links (`link` / `open_link`) and optional portrait lock

## 0.1.0
- Text-first screen reading, diff mode, tap/type/swipe/key/open, MCP server
