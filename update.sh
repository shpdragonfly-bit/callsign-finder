#!/bin/sh
# macOS / Linux: 인터넷 연결 상태에서 실행
cd "$(dirname "$0")" && python3 updater/update.py "$@"
