#!/bin/bash
# Отключает автозапуск сервиса и останавливает его.
set -euo pipefail
LABEL="ru.expenses.server"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Автозапуск отключён, сервис остановлен."
