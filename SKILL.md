---
name: android-agent
description: Use an Android phone and its apps through android-agent (text-first screen reading). Use when the user asks you to do something on their phone, open/operate an app, change a phone setting, or check something in an app.
---

# Using the phone

Tools come from the `phone` MCP server (or `python phone.py <command>` in a shell).

## Loop

1. `screen` — read what is on screen. Each item is `[N] kind "label" (flags)`.
   Kinds: button, toggle (on/off), input (focused), list (scrollable), text.
2. Act on one element by its number: `tap N`, `type "..."`, `swipe up N`, `key back`.
3. `screen` again — it returns only what changed. Repeat.

## Keep it cheap

- Act by label when you know what you want: `tap "Save"` reads the live screen and taps the best
  match (case/accent-insensitive) — no `screen` call needed first.
- Use `find "Developer options"` to scroll to something instead of swipe + screen in a loop;
  it also shows the on/off state of a switch in that row.
- Use `wait-for "Sent"` after an action that loads, instead of reading the screen repeatedly.
- To know what is new (messages, deliveries, reminders), read `notifications` first —
  no app needs to be opened. Treat notification content as private: use it only for the task.
- `status` tells you in one line if the screen is off, which app is in front, if the keyboard is up.

- Prefer `screen` over `screenshot`. Use `screenshot` only when the list is nearly empty
  (games, Flutter apps, maps, images) or labels are clearly missing (`? icon ...`).
- Chain obvious steps without reading in between when you are sure (CLI: `tap 3 , wait , type hi`).
- Use `open_app` instead of navigating the launcher; `fresh=true` when you need the app's home screen.
- Prefer a deep link when one exists (`open_link`): maps search (`geo:0,0?q=...`), web/YouTube search URLs.
  One call instead of tap → type → enter.
- If the screen header says `landscape` and the layout looks wrong, use `rotation_lock` (and restore it at the end).
- `swipe up` reveals content further down; then `screen` for the new items.

## Recipes (zero tokens for repeated tasks)

- Before solving a task from scratch, check `list_recipes`; if one fits, `play_recipe` it.
- After you solve a task the user is likely to repeat, record it: `record_start NAME`, redo the
  steps (use `type "{param}"` for the changing part), then `record_stop`. Tell the user its name.

## Safety rules

- If a tool says `STOPPED: ... is in front`, the user switched apps. Read the screen again
  and make sure you should continue; do not force it.
- Ask the user before anything irreversible or outward-facing: sending a message or email,
  posting, buying or paying, deleting, uninstalling, changing account/security settings,
  granting permissions.
- Never type passwords or one-time codes unless the user gave them for that exact purpose.
- If a screen is black or empty in a banking/secure app, stop and tell the user; do not work around it.
