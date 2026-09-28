#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --user pyinstaller
python3 -m PyInstaller --noconfirm --clean --onefile --name Romoteca main.py
tar -czf dist/Romoteca-linux-x86_64.tar.gz -C dist Romoteca
echo "Created dist/Romoteca-linux-x86_64.tar.gz"
