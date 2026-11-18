# Early benchmark (v0.1, 2026-11-18)

Device: Xiaomi Redmi Note 13 Pro, Android 16, wireless debugging from Termux on the same phone.
Token estimate = output characters / 3.5. Screenshot baseline = ~1,500 tokens per look.

| # | Task | Result | Screen reads |
|---|---|---|---|
| 1 | Settings → open Bluetooth page, read state | ok | 2 |
| 2 | YouTube → search "lofi", read results | ok (one mis-tap: the user pressed Back meanwhile; recovered) | 5 |
| 3 | Calculator → 12×34 (7 taps chained in one call) | ok, "= 408" | 2 |
| 4 | Clock → read alarm list | ok | 1 |
| 5 | Play Store → search "Termux", read result | ok | 4 |
| 6 | Maps → search a place | **failed**: search did not open (screen was in landscape; retest) | 5 |

Total: 19 screen reads, ~9,500 characters ≈ **~2,700 tokens**.
The same 19 looks as screenshots ≈ **~28,500 tokens** (~10× more).

## Found issues
- Maps: the search field is an input inside a clickable container; tapping either did not open search.
- The user (or autoplay) can change the screen between reading and tapping: verify the target right before tapping.
- `open` resumes the app where it was left (e.g. inside Shorts); a `--fresh` start is needed for repeatable tasks.
- Auto-rotate: one app opened in landscape. Report orientation in the screen header.
- Unlabeled controls (`? icon ...`) are common in Play Store and Maps.
