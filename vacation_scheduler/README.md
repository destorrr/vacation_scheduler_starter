# Vacation Scheduler

Веб-приложение для подготовки ежегодного графика отпусков Т-7.

**Стек:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Jinja2, Bootstrap 5, openpyxl, Docker Compose и Nginx.

## Возможности

- Центральный HR управляет организациями, кампаниями и ответственными пользователями.
- Ответственные видят только назначенные им организации.
- Сотрудники учитываются отдельно в каждой организации.
- Внутри организации сотрудник определяется по нормализованному ФИО; несколько должностей и табельных номеров связываются с одним планом отпусков.
- Оригиналы Excel сохраняются неизменными с версиями; повторная загрузка создаёт новую версию.
- Поддерживаются несколько периодов отпуска на сотрудника; продолжительность рассчитывается включительно в календарных днях.
- Экспорт создаёт отдельную копию шаблона Т-7; поддерживаются .xlsx и .xlsm.

## Развёртывание на Linux

Требуются Linux-сервер, Docker Engine с Compose plugin, Git и OpenSSL. Пример предполагает, что внешний reverse proxy или Nginx на сервере завершает HTTPS и проксирует запросы на локальный адрес `127.0.0.1:8080`. Сам контейнер Nginx не публикуется во внешнюю сеть.

### 1. Получить исходный код

Клонируйте репозиторий и переключитесь на согласованную ветку:

```bash
git clone https://github.com/destorrr/vacation_scheduler_starter.git
cd vacation_scheduler
git switch feature/auth-and-permissions
```

Перед эксплуатацией используйте проверенный commit из ветки, а не незакреплённый рабочий каталог.

### 2. Подготовить секреты и каталоги

```bash
cp .env.example .env
```

Сгенерируйте два разных секрета:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

Первое значение установите в `SECRET_KEY`, второе — в `POSTGRES_PASSWORD` файла `.env`. Пароль БД рекомендуется задавать hex-строкой, чтобы избежать проблем с URL-кодированием в строке подключения. Не используйте примеры и placeholder-значения из `.env.example`.

Затем ограничьте доступ к файлу и подготовьте постоянное хранилище:

```bash
chmod 600 .env
mkdir -p storage/originals storage/exports storage/temp backups
sudo chown -R 10001:10001 storage
chmod 700 storage
```

Контейнер приложения работает без root, под UID/GID 10001. При использовании другого способа монтирования storage обеспечьте этому пользователю право записи. Каталог `storage` содержит оригинальные шаблоны и готовые Excel-файлы — его нельзя терять при обновлении контейнера.

Проверьте, что подсеть Docker `172.30.0.0/24` не используется другой сетью на сервере. Если занята, измените подсеть и соответствующие статические адреса в `docker-compose.yml` и доверенный IP Nginx в `Dockerfile`.

### 3. Запустить сервисы

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Compose поднимает PostgreSQL, приложение и Nginx. Порт приложения 8000 не публикуется; Nginx доступен только на loopback-интерфейсе хоста: `127.0.0.1:8080`. База данных доступна только внутри Docker-сети. Данные PostgreSQL хранятся в именованном volume `postgres_data`, файлы приложения — в `./storage`.

Дождитесь статуса `healthy` у сервисов:

```bash
docker compose ps
curl -I http://127.0.0.1:8080/health
```

### 4. Применить миграции и создать центрального HR

```bash
docker compose exec app alembic upgrade head
docker compose exec app python -m app.cli create-admin
```

Команда создания администратора интерактивно запросит логин, ФИО и пароль. Минимальная длина пароля — 12 символов. Не создавайте начальную учётную запись через SQL вручную.

### 5. Доступ из локальной сети и HTTPS

Приложение рассчитано на работу внутри локальной сети организации. Публичный доступ из интернета не требуется. Рекомендуемая схема:

1. Выделите серверу постоянный IP-адрес в LAN.
2. Создайте внутреннюю DNS-запись, например `vacation.intra.example`, указывающую на этот IP. Если внутреннего DNS нет, на время проверки можно использовать локальный IP или запись в hosts на рабочих станциях.
3. Оставьте порт приложения Nginx опубликованным только на loopback: `127.0.0.1:8080`. Не открывайте 8080 и PostgreSQL для LAN или интернета.
4. На хосте установите Nginx или Caddy как TLS reverse proxy. Он должен слушать LAN-интерфейс на 443 и проксировать запросы на `http://127.0.0.1:8080`.
5. Используйте сертификат для внутреннего DNS-имени, выпущенный корпоративным/внутренним центром сертификации. Установите корневой сертификат этого центра на рабочие станции, чтобы браузеры доверяли HTTPS.
6. На межсетевом экране разрешите TCP/443 только из доверенных подсетей организации. Не создавайте проброс портов на маршрутизаторе из интернета.

Пример конфигурации host Nginx (замените имя и пути к сертификатам на свои):

```nginx
server {
    listen 80;
    server_name vacation.intra.example;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name vacation.intra.example;

    ssl_certificate     /etc/ssl/local/vacation.crt;
    ssl_certificate_key /etc/ssl/local/vacation.key;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

В `.env` оставьте `SESSION_HTTPS_ONLY=true`. Не отключайте Secure-cookie в штатной эксплуатации. Если HTTPS временно не настроен, не используйте такую конфигурацию для реальных пользовательских сессий: браузер не отправляет Secure-cookie по обычному HTTP.

Внутренний Nginx передаёт forwarded-заголовки приложению; Uvicorn доверяет им только от контейнера Nginx с адресом `172.30.0.10`. Не меняйте эту настройку на доверие произвольным адресам. Для ограничения перебора паролей endpoint `/login` ограничен на уровне Nginx: 5 запросов в минуту с небольшим burst. Внутренний Nginx доверяет `X-Real-IP` только от Docker gateway `172.30.0.1`; host reverse proxy должен перезаписывать этот заголовок реальным адресом клиента, а не принимать его от пользователя.

Порт `127.0.0.1:8080` предназначен только для локального reverse proxy на сервере. Если вы хотите временно тестировать приложение без host reverse proxy, выполняйте проверку на самом сервере через `curl http://127.0.0.1:8080/health`.

## Обновление приложения

1. Сделайте резервную копию БД и storage.
2. Перейдите на проверенный commit нужной ветки.
3. Выполните:

```bash
docker compose build app
docker compose up -d
docker compose exec app alembic upgrade head
docker compose ps
```

4. Проверьте вход, доступ ответственного к своей организации, загрузку шаблона и формирование Excel.

Не удаляйте volume `postgres_data` и каталог `storage`. Команда `docker compose down -v` удаляет volume базы данных и для штатного обновления не применяется.

## Резервное копирование

Создайте резервную копию из каталога проекта:

```bash
sh scripts/backup.sh
```

Скрипт создаёт два файла в `backups/`: сжатый SQL-дамп PostgreSQL и архив всего каталога storage. Бэкапы содержат персональные данные и документы сотрудников: ограничьте доступ к каталогу, шифруйте копии при переносе и храните хотя бы одну копию вне сервера. Настройте регулярный запуск через cron/systemd timer и периодически проверяйте восстановление на отдельном стенде.

### Восстановление

Восстановление перезаписывает текущие данные. Сначала остановите приложение и Nginx, затем восстановите БД и файлы из одной пары архивов:

```bash
docker compose stop app nginx
docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
gunzip -c backups/postgres-YYYYMMDDTHHMMSSZ.sql.gz | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
tar -xzf backups/storage-YYYYMMDDTHHMMSSZ.tar.gz -C .
sudo chown -R 10001:10001 storage
docker compose start app
docker compose exec app alembic upgrade head
docker compose start nginx
```

Замените имена архивов на файлы из одной даты резервного копирования. После восстановления проверьте вход и скачивание ранее сформированного Excel.

## Диагностика

```bash
docker compose ps
docker compose logs --tail=200 app
docker compose logs --tail=200 nginx
docker compose logs --tail=200 db
docker compose exec app alembic current
```

## Разработка и тесты

Для локального запуска задайте переменные окружения, включая уникальный `SECRET_KEY`, установите зависимости из `requirements.txt`, примените миграции и запустите:

```bash
uvicorn app.main:app --reload
pytest -q
```

Браузерный сценарий Playwright запускается отдельным workflow CI с Chromium и PostgreSQL.

## Важные эксплуатационные ограничения

- Перед открытием сервиса пользователям обязательны HTTPS, корректные forwarded-заголовки и защищённый `.env`.
- Секреты не должны попадать в Git, логи, резервные копии в открытом виде или тикеты.
- PostgreSQL и storage должны резервироваться совместно; восстановление только одной части может привести к отсутствующим файлам или записям.
- openpyxl не выполняет пересчёт формул Excel; при необходимости пересчёт выполняется в Excel или LibreOffice.
- После настройки домена и TLS необходимо провести приёмочную проверку с центральным HR и ответственным пользователем на сервере.
