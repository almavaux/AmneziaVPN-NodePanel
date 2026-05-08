# VesperVauxhall (MAX)

Минимальный поток без путаницы.

## Панель

Установка панели (на сервере):

```bash
curl -fsSL https://raw.githubusercontent.com/almavaux/AmneziaVPN-NodePanel/main/deploy.sh | bash -s -- install
```

После установки:

```bash
vvh menu
```

Или напрямую:

```bash
vvh update
vvh reinstall
vvh uninstall
vvh status
vvh logs
```

## Ноды

Node устанавливается и обновляется только из панели.

## Что важно

- Деплой панели: только `deploy.sh` из GitHub.
- Локальные ZIP-сценарии и лишние install-гайды удалены.
# awg-api

Лёгкий REST API для управления пирами [AmneziaWG](https://github.com/amnezia-vpn/amnezia-wg) без использования веб-панели Amnezia. Работает на том же хосте, что и Docker-контейнер AmneziaWG, и управляет им через Docker SDK (exec + файловый tar API).

## Master/Node control plane (gRPC + mTLS)

- `master` хранит веб-панель и локальный CA
- `node` после установки ждёт первичного подключения от master
- при подключении из панели master автоматически выполняет enrollment:
  - получает CSR с node
  - подписывает сертификат node
  - передаёт node сертификат и CA chain
  - node переключается в managed-режим (gRPC + mTLS)

Базовый поток:

1. Установить master (`AWG_ROLE=master`)
2. Установить node (`AWG_ROLE=node`, `AWG_MASTER_IP=<ip-master>`)
3. В панели master указать IP node и нажать `Connect node API`

После первичного подключения ручной ввод API key, port и scheme больше не нужен.
После успешного enrollment node блокируется на один master (`master.lock`) и bootstrap endpoint больше не используется.

## Возможности

- Список пользователей с live-статистикой трафика и временем последнего хендшейка
- Создание пира: генерация X25519-ключей, автовыделение IP, запись в конфиг и применение в ядро без рестарта AWG
- Удаление пира из конфига и из ядра
- Скачивание конфига клиента (`.conf` с Jc, S1-S4, H1-H4)
- Генерация QR-кода конфига
- Аутентификация по заголовку `X-API-Key`

## Требования к хосту

- Docker 20+ (проверено на Docker 29.1.3)
- Python-контейнер не нужен на хосте — всё запускается в Docker
- Доступ к Docker socket `/var/run/docker.sock`
- Запущенный контейнер AmneziaWG (по умолчанию `amnezia-awg2`)

## Установка панели (только один способ)

На сервере:

```bash
# Полная установка панели
curl -fsSL https://raw.githubusercontent.com/almavaux/AmneziaVPN-NodePanel/main/deploy.sh | bash -s -- install
```

После установки доступна команда:

```bash
vvh menu
```

В `vvh` есть действия:
- `update` (обновление панели),
- `reinstall` (чистая переустановка),
- `uninstall`,
- `status`,
- `logs`.

Обновление без меню:

```bash
vvh update
```

## Ноды

Node устанавливается и обновляется только из панели (через встроенный flow панели).  
Отдельные ручные сценарии деплоя node из CLI не рекомендуются.

### 1. Клонировать репозиторий

```bash
git clone <repo-url> /opt/awg-api
cd /opt/awg-api
```

Или скопировать файлы вручную — структура:

```
/opt/awg-api/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── auth.py
│   ├── docker_manager.py
│   ├── awg_manager.py
│   ├── main.py
│   └── routers/
│       ├── __init__.py
│       └── users.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env
```

### 2. Создать файл `.env`

```bash
cp .env.example .env
```

Отредактировать `.env`:

```env
AWG_API_KEY=ваш-секретный-ключ         # обязательно поменять!
AWG_SERVER_HOST=5.101.82.46            # внешний IP сервера (для Endpoint в конфиге клиента)
AWG_ALLOWED_IPS=203.0.113.10           # кто может вызывать API (обязательно в проде)
AWG_CONTAINER_NAME=amnezia-awg2        # имя Docker-контейнера с AmneziaWG
AWG_DNS=1.1.1.1                        # DNS для клиентов
```

Можно указать несколько адресов через запятую:

```env
AWG_ALLOWED_IPS=203.0.113.10,10.0.0.5
```

Сгенерировать безопасный ключ:

```bash
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

### Управление после установки

```bash
vvh menu
```

### 3. Собрать и запустить

**Вариант A — docker-compose** (если docker-compose-plugin установлен):

```bash
cd /opt/awg-api
docker compose up -d --build
```

**Вариант B — напрямую через docker** (если compose недоступен):

```bash
cd /opt/awg-api
docker build -t awg-api:latest .

docker run -d \
  --name awg-api \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --env-file /opt/awg-api/.env \
  --network amnezia-dns-net \
  awg-api:latest
```

> `amnezia-dns-net` — внешняя Docker-сеть, которую создаёт Amnezia. Если её нет, уберите `--network` — API всё равно подключится к `amnezia-awg2` через socket.

### 4. Проверить запуск

```bash
curl http://127.0.0.1:8000/health
# → {"status":"ok","container":"running"}
```

## API

Базовый URL: `http://127.0.0.1:8000`  
Аутентификация: заголовок `X-API-Key: <ваш ключ>`

> `client_id` в ответах — **base64url** (без `+`, `/`, `=`). Используй его как есть в URL-путях.

### GET /health

Проверка состояния сервиса и доступности контейнера AmneziaWG.

```bash
curl http://127.0.0.1:8000/health
```

```json
{"status": "ok", "container": "running"}
```

---

### GET /api/v1/users

Список всех пиров с live-статистикой.

```bash
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/users
```

```json
[
  {
    "client_id": "CGB3nTfcjqVzcoHqKVo8QcYpb8swNd1SKUZbmVshvzg",
    "name": "Admin",
    "internal_ip": "10.8.1.1",
    "created_at": "Sun Apr 12 01:32:58 2026",
    "transfer_rx": "29.11 KiB",
    "transfer_tx": "121.77 KiB",
    "last_handshake": "5 minutes ago",
    "is_online": true
  }
]
```

`is_online = true` если последний хендшейк был менее 3 минут назад.

---

### POST /api/v1/users

Создать нового пира.

```bash
curl -X POST \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "MyPhone"}' \
  http://127.0.0.1:8000/api/v1/users
```

```json
{
  "user": {
    "client_id": "ZB9QoEpso-VGNoy7M_9bUZDTBGpqJAmMCIwfTS76B1I",
    "name": "MyPhone",
    "internal_ip": "10.8.1.3",
    "created_at": "Sat Apr 11 23:10:17 2026"
  },
  "config": "[Interface]\nPrivateKey = ...\nAddress = 10.8.1.3/32\n..."
}
```

Ответ содержит готовый конфиг для импорта в AmneziaVPN / WireGuard. Пир применяется в ядро немедленно — без рестарта контейнера AmneziaWG.

---

### GET /api/v1/users/{client_id}/config

Скачать конфиг клиента в виде `.conf`-файла.

```bash
curl -H "X-API-Key: $KEY" \
  http://127.0.0.1:8000/api/v1/users/ZB9QoEpso-VGNoy7M_9bUZDTBGpqJAmMCIwfTS76B1I/config \
  -o myphone.conf
```

Конфиг содержит все AWG-параметры обфускации (`Jc`, `S1`–`S4`, `H1`–`H4`), готов для импорта в AmneziaVPN.

---

### GET /api/v1/users/{client_id}/qr

Получить QR-код конфига (PNG).

```bash
curl -H "X-API-Key: $KEY" \
  http://127.0.0.1:8000/api/v1/users/ZB9QoEpso-VGNoy7M_9bUZDTBGpqJAmMCIwfTS76B1I/qr \
  -o myphone_qr.png
```

---

### DELETE /api/v1/users/{client_id}

Удалить пира. Возвращает `204 No Content`.

```bash
curl -X DELETE \
  -H "X-API-Key: $KEY" \
  http://127.0.0.1:8000/api/v1/users/ZB9QoEpso-VGNoy7M_9bUZDTBGpqJAmMCIwfTS76B1I
```

## Обновление

```bash
cd /opt/awg-api
git pull   # или замени файлы вручную

# Вариант A (compose):
docker compose up -d --build

# Вариант B (прямой docker):
docker build -t awg-api:latest .
docker rm -f awg-api
docker run -d --name awg-api --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --env-file /opt/awg-api/.env \
  --network amnezia-dns-net \
  awg-api:latest
```

## Логи

```bash
docker logs awg-api -f
docker logs awg-api --tail 50
```

## Архитектура

```
Client → HTTPS (nginx/caddy) → http://127.0.0.1:8000 → awg-api container
                                                              │
                                                   Docker socket (read-only)
                                                              │
                                                    amnezia-awg2 container
                                                     ├── awg0.conf
                                                     ├── clientsTable (JSON)
                                                     └── awg set / awg showconf
```

- **Конфиг** читается/пишется через Docker tar API — не нужно монтировать volumes
- **Применение пиров** — `awg set awg0 peer ...` через `docker exec`, без рестарта
- **Live-статистика** — `awg show awg0` из ядра через UAPI, latency ~225ms
- **Блокировка** — `threading.Lock` вокруг create/delete во избежание race condition

## Настройка HTTPS (опционально)

API слушает только `127.0.0.1:8000`. Для внешнего доступа — реверс-прокси:

**Caddy** (автоматический TLS):

```
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## SSH, ключи и шифрование API

- SSH нужен только для деплоя и администрирования сервера.
- Runtime API-запросы идут по HTTP(S), не по SSH.
- Рекомендуемая защита: HTTPS (nginx/caddy) + `X-API-Key` + `AWG_ALLOWED_IPS`.
- Для строгого обмена ключами добавьте mTLS на прокси:
  - выпустить свой CA;
  - выдать клиентский сертификат вызывающему backend;
  - включить проверку клиентского сертификата на прокси.

**Nginx**:

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `AWG_API_KEY` | `change-me` | Секретный ключ для `X-API-Key` |
| `AWG_SERVER_HOST` | `5.101.82.46` | Внешний IP сервера (Endpoint в клиентском конфиге) |
| `AWG_ALLOWED_IPS` | `` | Разрешённые IP API-клиентов (через запятую) |
| `AWG_CONTAINER_NAME` | `amnezia-awg2` | Имя Docker-контейнера AmneziaWG |
| `AWG_CONF_PATH` | `/opt/amnezia/awg/awg0.conf` | Путь к конфигу внутри контейнера |
| `AWG_CLIENTS_TABLE_PATH` | `/opt/amnezia/awg/clientsTable` | Путь к метаданным клиентов |
| `AWG_PSK_KEY_PATH` | `/opt/amnezia/awg/wireguard_psk.key` | PSK для новых пиров |
| `AWG_SERVER_PUBKEY_PATH` | `/opt/amnezia/awg/wireguard_server_public_key.key` | Публичный ключ сервера |
| `AWG_DNS` | `1.1.1.1` | DNS-сервер для клиентов |
| `AWG_DOCKER_SOCKET` | `unix:///var/run/docker.sock` | Docker socket |

## Совместимость

Протестировано с:
- AmneziaWG container `amnezia-awg2`, `amneziawg-tools v1.0.20210914`
- Ubuntu 24.04.3 LTS, Docker 29.1.3
- Python 3.12, FastAPI 0.115, uvicorn 0.30.6

> **Примечание по `advanced-security`:** Версия `amneziawg-tools v1.0.20210914` не поддерживает флаг `advanced-security` per-peer. AWG-обфускация (Jc, Jmin, Jmax, S1–S4, H1–H4) настраивается на уровне интерфейса и применяется ко всем пирам автоматически.
