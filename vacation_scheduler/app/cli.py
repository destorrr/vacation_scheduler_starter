import argparse
import getpass
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models.entities import User
from app.security import hash_password


def create_admin() -> int:
    username = input("Имя пользователя central_hr: ").strip()
    full_name = input("ФИО пользователя: ").strip()
    if not username or not full_name:
        print("Имя пользователя и ФИО обязательны.", file=sys.stderr)
        return 1

    password = getpass.getpass("Пароль (минимум 12 символов): ")
    confirmation = getpass.getpass("Повторите пароль: ")
    if password != confirmation:
        print("Пароли не совпадают.", file=sys.stderr)
        return 1
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.username == username)):
            print("Такое имя пользователя уже существует.", file=sys.stderr)
            return 1
        user = User(
            username=username,
            full_name=full_name,
            password_hash=password_hash,
            role="central_hr",
            is_active=True,
        )
        db.add(user)
        db.commit()
    print(f"Пользователь central_hr '{username}' создан.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Утилиты Vacation Scheduler")
    parser.add_argument("command", choices=["create-admin"])
    args = parser.parse_args()
    if args.command == "create-admin":
        raise SystemExit(create_admin())


if __name__ == "__main__":
    main()
