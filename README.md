# Vacation Scheduler

Веб-приложение для подготовки ежегодного графика отпусков по форме Т-7.

Основной код приложения, конфигурация Docker Compose, миграции базы данных, тесты и эксплуатационная документация находятся в каталоге **[vacation_scheduler/](vacation_scheduler/)**.

## Быстрый переход

- [Основная инструкция: установка, настройка и эксплуатация](vacation_scheduler/README.md)
- [Развёртывание на Ubuntu и Debian через Docker Compose](vacation_scheduler/docs/deployment-linux.md)
- [Пример конфигурации окружения](vacation_scheduler/.env.example)
- [CI: автоматические проверки](.github/workflows/ci.yml)

## Клонирование

Рабочая версия проекта размещается в основной ветке `main`:

```bash
git clone https://github.com/destorrr/vacation_scheduler_starter.git
cd vacation_scheduler_starter/vacation_scheduler
```

Дальнейшие команды настройки и запуска приведены в [основной инструкции](vacation_scheduler/README.md#развёртывание-на-linux).

## Состав проекта

```text
.
├── .github/workflows/       # CI: тесты, E2E и Docker smoke test
├── vacation_scheduler/
│   ├── app/                 # FastAPI-приложение
│   ├── alembic/             # миграции PostgreSQL
│   ├── deploy/              # конфигурация внутреннего Nginx
│   ├── docs/                # инструкции по развёртыванию
│   ├── scripts/             # ручное резервное копирование
│   ├── tests/               # unit, integration и browser E2E
│   ├── storage/              # постоянное файловое хранилище
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── .env.example
│   └── README.md
└── ГРАФИК ОТПУСКОВ ООО  2026.xlsx  # пример исходного Excel-шаблона
```

## Требования и ограничения

- Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2, Alembic.
- Docker Engine и Docker Compose plugin для развёртывания.
- Предполагается работа в локальной сети организации через HTTPS reverse proxy.
- Секреты и реальные данные сотрудников не должны попадать в Git.
- Резервное копирование выполняется вручную скриптом `scripts/backup.sh`; автоматическое расписание в проект не включено.

Перед эксплуатацией прочитайте инструкции целиком и выполните приёмочную проверку на целевом сервере. Успешный CI не заменяет проверку конкретной инфраструктуры.
