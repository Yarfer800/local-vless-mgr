# vless-mgr

Parse free VLESS configs → probe → publish to Marzban + subscription feed with auto-balancer.

```
TXT sources (URL) → Parse vless:// → Probe servers (TCP+TLS) → Marzban users + Sing-box JSON subscription
```

---

## 🇷🇺 Русский

### Что это

Автоматический сборщик бесплатных VLESS-конфигов. Каждый час:
1. Скачивает TXT-файлы с vless:// ссылками
2. Парсит их (UUID, адрес, порт, TLS/Reality/WS/gRPC и т.д.)
3. Проверяет сервера (TCP + TLS handshake)
4. Отсеивает мёртвые и медленные (>1000ms)
5. Определяет страны через ip-api.com
6. Создаёт пользователей в Marzban
7. Генерирует подписку с url-test balancer'ом

### Быстрый старт

```bash
git clone <repo> && cd vless-mgr
mkdir -p data
docker compose up -d
```

Создать админа в Marzban (один раз):
```bash
docker compose exec marzban sh -c 'printf "\n\n" | python /code/marzban-cli.py admin create -u admin --sudo'
```
Пароль: `admin`

### Эндпоинты

| Ссылка | Формат | Для кого |
|---|---|---|
| `http://localhost:8080/sub` | **Sing-box JSON** | 55+ серверов + url-test 🇺🇳 Best (авто-пинг, переключение на лучший) |
| `http://localhost:8080/sub.txt` | Plain text | v2rayNG, Hiddify, Nekobox, V2Box, Streisand и любые другие |
| `http://localhost:8080/best` | Plain text | Только топ-10 быстрых |
| `http://localhost:8000` | Web UI | Панель Marzban |

### Как работает balancer

В `/sub` (JSON формат Sing-box) добавляется специальный outbound типа `urltest`:

```json
{
  "type": "urltest",
  "tag": "🇺🇳 Best",
  "outbounds": ["V01", "V02", ..., "V55"],
  "url": "http://www.gstatic.com/generate_204",
  "interval": "1m"
}
```

При импорте в Sing-box ты получаешь:
- 55 отдельных серверов (V01–V55) — можно выбирать вручную
- 🇺🇳 Best — автоматический режим: каждую минуту пингует все сервера и переключается на самый быстрый

### Настройка

В `.env` или напрямую в `src/config.py`:

| Параметр | ENV | Дефолт | Описание |
|---|---|---|---|
| Источники | `SOURCES` | Epodonios GitHub | TXT-файлы с vless:// |
| Бэкенд | `BACKEND` | `marzban` | json / marzban / all |
| Сэмпл | `PROBE_SAMPLE` | `300` | Сколько серверов проверять |
| Таймаут | `PROBE_TIMEOUT` | `5` | Секунд на один сервер |
| Параллельно | `PROBE_CONCURRENCY` | `20` | Одновременных проверок |
| Интервал | `INTERVAL` | `3600` | Секунд между циклами |
| Порт подписки | `SUB_PORT` | `8080` | HTTP |

### Управление

```bash
# Статус
docker compose ps

# Логи сборщика
docker compose logs vless-mgr --tail 50

# Логи подписки
docker compose logs sub-server --tail 10

# Принудительно запустить цикл
docker compose restart vless-mgr

# Пересобрать и запустить
docker compose up -d --build vless-mgr

# Остановить всё
docker compose down
```

### Требования

- Docker + Docker Compose (плагин v2)
- Linux / macOS / Windows WSL2

---

## 🇬🇧 English

### What it is

An automated VLESS config collector. Every hour:
1. Downloads TXT files with vless:// links
2. Parses them (UUID, address, port, TLS/Reality/WS/gRPC, etc.)
3. Probes servers (TCP + TLS handshake)
4. Filters dead & slow (>1000ms) servers
5. Resolves countries via ip-api.com
6. Creates Marzban users
7. Generates a subscription feed with an auto-url-test balancer

### Quick start

```bash
git clone <repo> && cd vless-mgr
mkdir -p data
docker compose up -d
```

First-time Marzban admin setup:
```bash
docker compose exec marzban sh -c 'printf "\n\n" | python /code/marzban-cli.py admin create -u admin --sudo'
```
Password: `admin`

### Endpoints

| URL | Format | Purpose |
|---|---|---|
| `http://localhost:8080/sub` | **Sing-box JSON** | 55+ servers + url-test 🇺🇳 Best (auto-ping, switches to fastest) |
| `http://localhost:8080/sub.txt` | Plain text | v2rayNG, Hiddify, Nekobox, V2Box, Streisand, any client |
| `http://localhost:8080/best` | Plain text | Top 10 fastest only |
| `http://localhost:8000` | Web UI | Marzban panel |

### How the balancer works

The `/sub` endpoint (Sing-box JSON) includes an `urltest` outbound:

```json
{
  "type": "urltest",
  "tag": "🇺🇳 Best",
  "outbounds": ["V01", "V02", ..., "V55"],
  "url": "http://www.gstatic.com/generate_204",
  "interval": "1m"
}
```

When imported into Sing-box you get:
- 55 individual servers (V01–V55) — pick manually
- 🇺🇳 Best — auto mode: pings all servers every minute, switches to the fastest

### Configuration

In `.env` or directly in `src/config.py`:

| Parameter | ENV | Default | Description |
|---|---|---|---|
| Sources | `SOURCES` | Epodonios GitHub | TXT file URLs with vless:// |
| Backend | `BACKEND` | `marzban` | json / marzban / all |
| Sample | `PROBE_SAMPLE` | `300` | How many servers to probe |
| Timeout | `PROBE_TIMEOUT` | `5` | Seconds per server |
| Concurrency | `PROBE_CONCURRENCY` | `20` | Parallel probes |
| Interval | `INTERVAL` | `3600` | Seconds between cycles |
| Sub port | `SUB_PORT` | `8080` | HTTP |

### Management

```bash
docker compose ps
docker compose logs vless-mgr --tail 50
docker compose logs sub-server --tail 10
docker compose restart vless-mgr
docker compose up -d --build vless-mgr
docker compose down
```

### Requirements

- Docker + Docker Compose (v2 plugin)
- Linux / macOS / Windows WSL2

---

## Architecture

```
┌────────┐   ┌────────┐   ┌────────┐   ┌──────────────┐
│  TXT   │──▶│ Parser │──▶│ Prober │──▶│  Marzban     │
│  URLs  │   │vless://│   │TCP+TLS │   │  (users)     │
└────────┘   └────────┘   └────────┘   └──────────────┘
                              │                │
                              ▼                ▼
                        ┌──────────┐    ┌──────────┐
                        │ GeoIP    │    │/sub JSON │
                        │ ip-api   │    │+url-test │
                        └──────────┘    └──────────┘
```

### Modules

- `src/parser.py` — VLESS URI parser (TCP/WS/gRPC/KCP + TLS/Reality)
- `src/fetcher.py` — Async HTTP downloader
- `src/prober.py` — TCP + TLS probe with timeouts
- `src/collector.py` — Pipeline: fetch → parse → probe → GeoIP → subscription writer
- `src/backends/marzban.py` — Marzban API: auto-enable VLESS, create users
- `src/backends/json_file.py` — JSON file output
- `src/backends/xray_outbound.py` — Xray outbound config generator
- `src/config.py` — Pydantic settings

### Docker services

| Service | Image | Purpose |
|---|---|---|
| `mysql` | mysql:8.0 | Marzban database |
| `marzban` | gozargah/marzban | Panel + Xray |
| `vless-mgr` | local (build) | Collector daemon |
| `sub-server` | python:3.12-slim | Serves subscriptions |

## License

MIT
