#!/bin/bash
# Автозапуск сервиса при входе пользователя в macOS (launchd).
# Сервис перезапускается сам, если упадёт. Отключить: scripts/uninstall_autostart.sh
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="ru.expenses.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$PROJECT/data/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$PROJECT/scripts/run_server.sh</string></array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$PROJECT/data/logs/server.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/data/logs/server.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<IP этого компьютера>')"
echo "Автозапуск включён. Сервис: http://$IP:${PORT:-8000}"
echo "Журнал: $PROJECT/data/logs/server.log"
echo "Для AI-анализа включите автозапуск Ollama: значок Ollama в строке меню → Settings → Launch at login."
