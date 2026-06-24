# GrindVacPro

**GrindVacPro** — асинхронная система автоматизации поиска вакансий. Собирает вакансии с платформ (hh.ru, career.habr.com), фильтрует по семантическому сходству с резюме через локальную ML-модель (rubert-tiny2), анализирует подходящие вакансии через LLM и отправляет карточки в Telegram.

## Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐     ┌──────────────────┐
│   Scraper   │────>│  Transformer │────>│  Analyzer  │────>│  Telegram Bot    │
│ (curl_cffi) │     │ (arq, CPU×1) │     │(arq, IO×10)│     │(aiogram 3 + arq) │
└──────┬──────┘     └──────┬───────┘     └─────┬──────┘     └──────────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
┌──────────────────────────────────────────────────────┐
│              PostgreSQL 18 + pgvector                │
│    vacancies │ vacancy_links │ HNSW-индекс (312-dim) │
└──────────────────────────────────────────────────────┘
                          ▲
                          │
                   ┌──────┴───────┐
                   │   Redis 7    │
                   │   (arq)      │
                   │  html_queue  │
                   │  ai_queue    │
                   │telegram_queue│
                   └──────────────┘
```

### Пайплайн обработки

1. **Scraper** → собирает URL из поисковой выдачи (`search_queries.json`), скачивает HTML-страницы, парсит через CSS-селекторы из `selectors.json`, сохраняет в `vacancies` + `vacancy_links`, ставит задачу в `html_queue`. Rate limit: ≤5 запросов за 6 секунд.
2. **Transformer** (arq, `max_jobs=1`) → HTML→Markdown (MarkItDown), SHA-256 дедупликация, чанкинг (1200 символов, overlap=2), cosine similarity с резюме через rubert-tiny2, порог настраивается через `SIMILARITY_THRESHOLD` (по умолчанию 0.70), сохраняет вектор лучшего чанка в `vacancies.embedding`, ставит задачу в `ai_queue`.
3. **Analyzer** (arq, `max_jobs=10`) → отправляет Markdown в LLM (AsyncOpenAI), получает структурированный JSON (`score`, `pros`, `cons`, `cover_letter`), сохраняет в `vacancies.ai_analysis`. Если `score >= AI_SCORE_THRESHOLD` (по умолчанию 50), ставит задачу в `telegram_queue`; иначе пропускает уведомление.
4. **Telegram Bot** → единый процесс: `aiogram 3` (polling) + `arq` (воркер). Статeless inline-кнопки, двухэтапное подтверждение (карточка → действие → причина). По завершении сохраняет `status` (`accepted`/`declined`) и `notes` (причина) в БД.

### Статусы ссылок (`vacancy_links.status`)

| Значение       | Описание                                                                 |
|----------------|--------------------------------------------------------------------------|
| `new`          | Ссылка собрана, ожидает обработки                                        |
| `parsed`       | HTML скачан и разобран, задача в transformer                             |
| `processed`    | LLM-анализ завершён; уведомление в Telegram отправлено, если score ≥ порог |
| `rejected`     | Не прошёл фильтр similarity (`< SIMILARITY_THRESHOLD`)                   |
| `accepted`     | Пользователь принял вакансию через Telegram                              |
| `declined`     | Пользователь отказался от вакансии через Telegram (причина в `Vacancy.notes`) |
| `failed`       | Ошибка при скачивании, парсинге или LLM-анализе                          |

## Стек

| Компонент       | Технология                              |
|-----------------|-----------------------------------------|
| Язык            | Python 3.12 (строгая асинхронность)     |
| HTTP-клиент     | `curl_cffi` (TLS/JA3 bypass)           |
| БД              | PostgreSQL 18 + pgvector                |
| Очереди         | Redis 7 + arq                           |
| ML (embedding)  | `SentenceTransformer('rubert-tiny2')`   |
| HTML→Markdown   | Microsoft MarkItDown                    |
| LLM             | OpenAI API (AsyncOpenAI)                |
| Telegram        | `aiogram 3.x`                           |
| Конфигурация    | pydantic-settings v2                    |
| Containerize    | Docker Compose                          |

## Структура проекта

```text
GrindVacPro/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── AGENTS.md                        # Глобальные стандарты кодинга
├── CONTEXT.md                       # Архитектурный контекст
├── README.md                        # Этот файл
│
├── infra/postgres/init.sql          # Инициализация БД (pgvector, таблицы, индексы)
│
├── shared/                          # Общее ядро
│   ├── requirements.txt
│   ├── resume.txt                   # Текст резюме для семантического сравнения
│   └── src/
│       ├── config.py                # pydantic-settings
│       ├── database.py              # async engine + session maker
│       ├── models.py                # ORM-модели Vacancy, VacancyLink
│       ├── security.py              # SSRF-защита, валидация URL
│       ├── selectors.py             # Загрузчик селекторов платформ
│       └── utils/
│           ├── logger.py            # Унифицированный логгер
│           ├── crypto.py            # SHA-256
│           └── url.py               # Нормализация URL
│
└── services/
    ├── scraper/                     # Сбор данных (Network I/O)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── selectors.json           # CSS-селекторы платформ
    │   ├── search_queries.json      # Параметры поисковых запросов
    │   └── src/
    │       ├── main.py              # Оркестратор
    │       ├── search.py            # Сбор URL
    │       └── pipeline.py          # Скачивание + парсинг
    │
    ├── transformer/                 # Фильтрация (CPU-bound)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── resume.txt               # Сymлicky копия резюме для контейнера
    │   └── src/worker.py            # arq-воркер (max_jobs=1)
    │
    ├── analyzer/                    # LLM-анализ (Network I/O)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── resume.txt               # Сymлicky копия резюме для контейнера
    │   └── src/
    │       ├── worker.py            # arq-воркер (max_jobs=10)
    │       └── prompts.py           # Системный промпт
    │
    └── telegram_bot/                # Telegram-уведомления (aiogram 3 + arq)
        ├── Dockerfile
        ├── requirements.txt
        └── src/
            ├── main.py              # aiogram polling + arq worker
            ├── worker.py            # send_vacancy_notification
            ├── callbacks.py         # Stateless callback router
            ├── keyboards.py         # Inline keyboard builders
            └── messages.py          # Форматирование карточек
```

## Запуск

### 1. Подготовка окружения

```bash
cp .env.example .env
# Отредактируйте .env — укажите OPENAI_API_KEY, TELEGRAM_BOT_TOKEN и т.д.
```

Резюме хранится в файле `shared/resume.txt` и монтируется в контейнеры `transformer` и `analyzer` как read-only volume. Переменная окружения `TARGET_RESUME` не используется.

### 2. Запуск через Docker Compose

```bash
docker compose up -d --build
```

Это поднимет:
- `postgres:5432` — PostgreSQL 18 + pgvector
- `redis:6379` — Redis 7
- `grindvac-scraper` — сбор и парсинг данных
- `grindvac-transformer` — CPU-bound фильтрация
- `grindvac-analyzer` — LLM-анализ
- `grindvac-telegram-bot` — Telegram-уведомления и inline-кнопки

### 3. Проверка состояния

```bash
# Логи
docker compose logs -f scraper
docker compose logs -f transformer
docker compose logs -f analyzer
docker compose logs -f telegram_bot

# Статус контейнеров
docker compose ps
```

### 4. Подключение к БД

```bash
docker exec -it grindvac-postgres psql -U grindvac -d grindvac
```

## Конфигурация (.env)

| Переменная              | Описание                                         | По умолчанию                         |
|-------------------------|--------------------------------------------------|--------------------------------------|
| `POSTGRES_DB`           | Имя базы данных                                  | `grindvac`                           |
| `POSTGRES_USER`         | Пользователь БД                                  | `grindvac`                           |
| `POSTGRES_PASSWORD`     | Пароль БД                                        | `grindvac_secret`                    |
| `DATABASE_URL`          | SQLAlchemy async DSN                             | `postgresql+asyncpg://...`           |
| `REDIS_URL`             | Redis DSN                                        | `redis://localhost:6379`             |
| `OPENAI_API_KEY`        | Ключ OpenAI-совместимого API                     | *(обязательно)*                      |
| `OPENAI_BASE_URL`       | Базовый URL API                                  | `https://api.openai.com/v1`          |
| `OPENAI_MODEL_NAME`     | Модель LLM                                       | `gpt-4o-mini`                        |
| `AI_SCORE_THRESHOLD`    | Минимальный score для уведомления в Telegram     | `50`                                 |
| `SIMILARITY_THRESHOLD`  | Минимальное cosine similarity для фильтрации     | `0.70`                               |
| `TELEGRAM_BOT_TOKEN`    | Token Telegram-бота                              | *(обязательно для telegram_bot)      |
| `TELEGRAM_USER_ID`      | ID пользователя, который может управлять ботом   | *(обязательно для telegram_bot)      |

## Rate Limiting

Scraper ограничен **5 запросов за 6 секунд**: `await asyncio.sleep(random.uniform(1.0, 1.5))` перед каждым запросом. При ошибках скачивания — экспоненциальный backoff с джиттером (до 3 попыток).

## Дедупликация

- **По URL**: нормализация (stripping query-параметров и фрагментов) → `UNIQUE(vacancy_links.url)` + `ON CONFLICT DO NOTHING`
- **По контенту**: SHA-256 от Markdown-текста вакансии → `UNIQUE(vacancies.content_hash)`. Дубликаты перепривязываются к существующей вакансии, ссылка получает статус `rejected`.

## Telegram Bot

Сервис работает в одном процессе: `aiogram 3` polling (background task) + `arq` worker (main task). Логика управления полностью stateless — состояние передаётся через `callback_data` (`vac:{id}:{action}:{idx?}`), без FSM. Flow:

1. **Карточка вакансии** (`show`) — заголовок, компания, score, pros/cons, cover_letter в `<code>`-теге, кнопки `[❌ Отказался]` / `[✔️ Откликнулся]`
2. **Подтверждение** (`ca`/`cr`) — промежуточный экран «Вы уверены?» с кнопками `[Подтвердить]` / `[Назад]`
3. **Причина** (`pa`/`pr` → `ra`/`rd`) — выбор причины из фиксированного списка; статус и причина сохраняются в БД

При отправке карточки кнопка `reply_markup` прикрепляется к сообщению, чтобы пользователь мог вернуться к карточке. После сохранения причины клавиатура скрывается.

## Добавление новых платформ

1. Добавьте CSS-селекторы в `services/scraper/selectors.json`:
```json
{
  "example.com": {
    "searcher": { "vacancy_link": "a.job-link" },
    "parser": {
      "title": "h1.job-title",
      "company_name": "span.company",
      "description": "div.description"
    }
  }
}
```
2. Добавьте параметры поиска в `services/scraper/search_queries.json`:
```json
{
  "example.com": {
    "base_url": "https://example.com/jobs",
    "params": ["query=python&remote=true"],
    "use_pages_limiter": false,
    "pages": 1
  }
}
```
3. При необходимости добавьте slug-маппинг в `services/scraper/src/search.py` и `services/scraper/src/pipeline.py`: `_PLATFORM_SLUGS["example.com"] = "example"`
4. Пересоберите и запустите: `docker compose up -d --build`
