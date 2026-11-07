# Установка Docker и запуск Vacation Scheduler на Ubuntu / Debian

Инструкция предназначена для установки Docker Engine из официального репозитория Docker и запуска приложения в локальной сети. Команды рассчитаны на Ubuntu и Debian с systemd и архитектуру, поддерживаемую Docker.

Официальные инструкции:
- [Docker Engine — Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Docker Engine — Debian](https://docs.docker.com/engine/install/debian/)
- [Docker Compose plugin для Linux](https://docs.docker.com/compose/install/linux/)

## 1. Проверить ОС и архитектуру

```bash
cat /etc/os-release
dpkg --print-architecture
```

Для Debian используйте поддерживаемый Docker релиз (на текущей странице Docker указаны Debian 12 и 13). Для Ubuntu сверяйте версию с актуальным списком поддерживаемых выпусков в официальной документации Docker.

## 2. Установить Docker Engine

Не смешивайте пакеты Docker из репозитория дистрибутива и официальный набор Docker. Если ранее установлен `docker.io`, `docker-compose`, `docker-compose-v2`, `podman-docker`, `containerd` или `runc`, сначала проверьте, что от них не зависят другие контейнерные сервисы. При необходимости удалите конфликтующие пакеты по инструкции Docker. Не удаляйте каталоги данных Docker без отдельного решения: там могут находиться существующие контейнеры и volumes.

### Ubuntu

```bash
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Debian

```bash
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

В обоих случаях включите автозапуск и проверьте версии:

```bash
sudo systemctl enable --now docker
sudo systemctl status docker --no-pager
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

Для дальнейших команд можно использовать `sudo docker ...`. Добавление пользователя в группу `docker` избавляет от `sudo`, но фактически предоставляет ему права уровня root. Делайте это только для доверенной административной учётной записи; не добавляйте в эту группу обычных пользователей приложения.

## 3. Подготовить проект

Клонируйте репозиторий и перейдите в каталог приложения:

```bash
git clone https://github.com/destorrr/vacation_scheduler_starter.git
cd vacation_scheduler_starter
git switch feature/auth-and-permissions
cd vacation_scheduler
```

Перед эксплуатацией зафиксируйте проверенный commit, прошедший CI. Не обновляйте сервер автоматически до произвольного последнего состояния ветки.

Создайте файл конфигурации и секреты:

```bash
cp .env.example .env
openssl rand -hex 32
openssl rand -hex 32
```

Первый секрет задайте как `SECRET_KEY`, второй — как `POSTGRES_PASSWORD` в `.env`. Не используйте одни и те же значения. Затем:

```bash
chmod 600 .env
mkdir -p storage/originals storage/exports storage/temp backups
sudo chown -R 10001:10001 storage
chmod 700 storage
```

Пользователь приложения внутри контейнера имеет UID/GID 10001 и должен иметь право записи в `storage`.

## 4. Проверить Docker Compose и запустить приложение

```bash
sudo docker compose config --quiet
sudo docker compose up -d --build
sudo docker compose ps
```

Проверьте health endpoint на самом сервере:

```bash
curl -fsS http://127.0.0.1:8080/health
```

Порт 8080 должен быть привязан только к loopback. PostgreSQL не должен иметь опубликованного host-порта. Не меняйте эти ограничения ради доступа рабочих станций: для пользователей нужен host reverse proxy с HTTPS.

Создайте учётную запись центрального HR:

```bash
sudo docker compose exec app alembic upgrade head
sudo docker compose exec app python -m app.cli create-admin
```

Команда интерактивно запросит логин, ФИО и пароль (не менее 12 символов).

## 5. LAN, HTTPS и firewall

Для рабочего доступа из локальной сети настройте внутреннее DNS-имя, host Nginx или Caddy с TLS-сертификатом от внутреннего CA и доступ по TCP/443 только из доверенных LAN-подсетей. Корневой сертификат CA должен быть установлен на рабочих станциях. В `.env` оставьте `SESSION_HTTPS_ONLY=true`.

Не публикуйте 8080 или PostgreSQL в LAN/интернет и не настраивайте проброс портов на маршрутизаторе. Docker управляет собственными правилами firewall; при настройке UFW/nftables учитывайте рекомендации Docker по firewall и не полагайтесь только на UFW для защиты опубликованных Docker-портов. В текущем Compose порт Nginx привязан к `127.0.0.1:8080`, а у PostgreSQL host-порт отсутствует.

Если подсеть `172.30.0.0/24` занята, выберите свободную Docker-подсеть и синхронно измените:
- subnet и статические IP в `docker-compose.yml`;
- адрес доверенного proxy в параметре `--forwarded-allow-ips` в `Dockerfile`;
- адрес Docker gateway в директиве `set_real_ip_from` в `deploy/nginx.conf`.

Не расширяйте доверие proxy до произвольных адресов.

## 6. Обновление

Перед обновлением создайте резервную копию БД и `storage`. Затем переключитесь на заранее проверенный commit:

```bash
git fetch origin
git checkout <проверенный-commit>
sudo docker compose build app
sudo docker compose up -d
sudo docker compose exec app alembic upgrade head
sudo docker compose ps
```

Не используйте `docker compose down -v`: эта команда удаляет volume базы данных.

## 7. Резервное копирование и восстановление

Из каталога `vacation_scheduler` выполните:

```bash
sudo sh scripts/backup.sh
```

Скрипт сохраняет SQL-дамп PostgreSQL и архив каталога `storage` в `backups/`. Ограничьте права на резервные копии, шифруйте их при переносе и храните копию вне сервера. Настройте расписание через cron или systemd timer и регулярно проверяйте восстановление на отдельном стенде. Процедура восстановления приведена в основном [README](../README.md#восстановление).

## 8. Приёмочная проверка

После настройки HTTPS проверьте с рабочей станции:
- открытие внутреннего DNS-имени без предупреждения о сертификате;
- вход центрального HR и создание ответственного;
- вход ответственного и видимость только назначенной организации;
- загрузку оригинального Excel-шаблона;
- ввод нескольких периодов отпуска и экспорт заполненного Excel;
- доступность приложения после перезагрузки сервера;
- создание резервной копии и тестовое восстановление на отдельном стенде.

CI проекта проверяет приложение и Docker Compose smoke test на Ubuntu runner. Это не является подтверждением полноценного тестирования на конкретном сервере Debian: перед эксплуатацией выполните установку и приёмочную проверку на целевой машине.
