#!/bin/sh
# phone-agent setup: connect adb to this phone (Termux) or to another phone, and remember it.
# Usage:  sh setup.sh            interactive
#         sh setup.sh HOST:PORT  connect directly (pairing must already be done)
set -e
CONF="$HOME/.config/phone-agent"
mkdir -p "$CONF"

need() { command -v "$1" >/dev/null 2>&1; }

if ! need adb; then
  if need pkg; then
    echo "adb not found. Installing android-tools (Termux)..."
    pkg install -y android-tools
  else
    echo "adb not found. Install Android platform-tools (e.g. 'sudo apt install adb') and run again."
    exit 1
  fi
fi
need python3 || { echo "python3 is required (Termux: pkg install python)"; exit 1; }

if [ -n "$1" ]; then
  SERIAL="$1"
else
  cat <<'EOF'

On the phone you want to control:
  1. Settings > Developer options > turn on "USB debugging" and "Wireless debugging".
     Xiaomi/Redmi/POCO: also turn on "USB debugging (Security settings)" (needed for taps).
  2. First time only: Wireless debugging > "Pair device with pairing code".
     If this is the same phone, open Termux and Settings in split screen so the code stays visible.

EOF
  printf "Pair now? Enter PAIR_HOST:PAIR_PORT (or leave empty to skip): "
  read -r PAIR
  if [ -n "$PAIR" ]; then
    printf "Pairing code: "
    read -r CODE
    adb pair "$PAIR" "$CODE"
  fi
  echo
  echo 'Now enter the address shown under "IP address & Port" on the Wireless debugging screen.'
  echo "On the same phone you can use 127.0.0.1 with that port."
  printf "HOST:PORT: "
  read -r SERIAL
fi

adb connect "$SERIAL"
adb -s "$SERIAL" get-state >/dev/null 2>&1 || { echo "Could not connect to $SERIAL"; exit 1; }
echo "$SERIAL" > "$CONF/serial"
echo "Saved device $SERIAL to $CONF/serial"

DIR=$(cd "$(dirname "$0")" && pwd)
python3 "$DIR/phone.py" screen --full | head -5

if need claude; then
  printf "Register the MCP server with Claude Code? [y/N] "
  read -r ans
  case "$ans" in
    y|Y) claude mcp add phone -- python3 "$DIR/mcp_server.py" && echo "Added MCP server 'phone'." ;;
  esac
fi
echo "Done. Try: python3 $DIR/phone.py screen"
