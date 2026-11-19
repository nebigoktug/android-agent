# Changelog

## 0.5.0 (2026-11-19)
- Companion app: status light (green working / yellow idle / red needs you / grey paused),
  accessibility button = emergency pause, "needs you" card with the assistant's question
- `signal attention|idle` (CLI + MCP); agent.py turns the light red while it waits for your answer
- Taps fall back to adb when Android blocks accessibility gestures (permission dialogs)
- OCR items can be tapped by number

## 0.4.0 (2026-11-19)
- Optional companion app (accessibility service): ~7× faster screen reads, works during video,
  direct Unicode typing; local-only with a private key, visible action log, pause switch; EN/TR UI
- `ocr`: read text from apps that expose none (games, Flutter) with Tesseract; tappable by number
- `agent.py` (experimental): run a whole task from plain language with Claude or any
  OpenAI-compatible endpoint; asks before irreversible steps
- SKILL: close unexpected pop-ups, never confirm casts/purchases/permissions not asked for

## 0.3.0
- Act without agent turns: `tap "label"`, `find` (scrolls to it), `wait-for`
- Unlabeled switches take the name of their row; duplicate row/checkbox switches merged
- `notifications` and `status`: know what is new and the phone's state without opening apps
- Recipes: `record` / `stop` / `play` (with {params}) — repeated tasks cost zero tokens
- MCP: tap_label, find, wait_for, notifications, status, record/play recipes (20 tools)

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
