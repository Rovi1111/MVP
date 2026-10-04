#!/bin/bash
# Запуск сервиса для офисной сети: обновляет схему БД и слушает все сетевые интерфейсы.
# Адрес и порт можно переопределить: HOST=127.0.0.1 PORT=9000 scripts/run_server.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "Не найдено окружение .venv — выполните установку по README.md" >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "Не найден файл .env — скопируйте .env.example и задайте SECRET_KEY (см. README.md)" >&2
  exit 1
fi

.venv/bin/python -m alembic upgrade head
exec .venv/bin/python -m uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
