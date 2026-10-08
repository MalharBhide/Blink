#!/bin/bash
cd "$(dirname "$0")" || exit 1
python3 scripts/launch.py --stop
result=$?
if [ "$result" -ne 0 ]; then read -r -p 'Press Return to close this window.'; fi
exit "$result"
