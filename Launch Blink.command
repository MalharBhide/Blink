#!/bin/bash
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 scripts/launch.py
else
  echo 'Install Python from https://www.python.org/downloads/, then open Launch Blink again.'
  exit 1
fi
result=$?
if [ "$result" -ne 0 ]; then read -r -p 'Press Return to close this window.'; fi
exit "$result"
