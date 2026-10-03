"""Команды администрирования: python -m app.cli <команда>."""

import argparse
import getpass
import sys

from app.db import SessionLocal
from app.errors import AppError
from app.services.users import create_admin


def _cmd_create_admin(args: argparse.Namespace, session_factory=SessionLocal) -> int:
    password = args.password
    if not password:
        password = getpass.getpass("Пароль: ")
        if password != getpass.getpass("Пароль ещё раз: "):
            print("Пароли не совпадают", file=sys.stderr)
            return 1
    with session_factory() as db:
        try:
            user = create_admin(db, args.org, args.login, password, args.name or "")
        except AppError as exc:
            print(f"Ошибка: {exc.message}", file=sys.stderr)
            return 1
    print(f"Администратор «{user.login}» создан в организации «{args.org}»")
    return 0


def _cmd_seed(args: argparse.Namespace, session_factory=SessionLocal) -> int:
    from app import seed

    with session_factory() as db:
        try:
            messages = seed.seed(db, args.password or seed.DEFAULT_PASSWORD)
        except AppError as exc:
            print(f"Ошибка: {exc.message}", file=sys.stderr)
            return 1
    print("\n".join(messages))
    if not args.password:
        print("Пароль демо-пользователей — константа DEFAULT_PASSWORD в app/seed.py")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Учёт расходов: CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="создать администратора (и организацию)")
    admin.add_argument("--org", required=True, help="название организации")
    admin.add_argument("--login", required=True)
    admin.add_argument("--name", help="ФИО")
    admin.add_argument("--password", help="если не указан, будет запрошен интерактивно")
    admin.set_defaults(func=_cmd_create_admin)

    demo = sub.add_parser("seed", help="создать демо-организации с данными")
    demo.add_argument(
        "--password", help="пароль демо-пользователей (по умолчанию — из app/seed.py)"
    )
    demo.set_defaults(func=_cmd_seed)
    return parser


def main(argv: list[str] | None = None, session_factory=SessionLocal) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, session_factory)


if __name__ == "__main__":
    sys.exit(main())
