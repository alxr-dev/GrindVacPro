# GrindVacPro

**GrindVacPro** — асинхронная система автоматизации поиска вакансий. Собирает вакансии с платформ (hh.ru, career.habr.com), фильтрует по семантическому сходству с резюме через локальную ML-модель (rubert-tiny2), анализирует подходящие вакансии через LLM и генерирует сопроводительные письма.

## Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│   Scraper   │────▶│  Transformer  │────▶│  Analyzer  │
│ (curl_cffi) │     │ (arq, CPU×1) │     │(arq, IO×15)│
└──────┬──────┘     └──────┬───────┘     └─────┬──────┘
       │                   │                    │
       ▼                   ▼                    ▼
┌──────────────────────────────────────────────────────┐
│              PostgreSQL 18 + pgvector                 │
│    vacancies │ vacancy_links │ HNSW-индекс (312-dim) │
└──────────────────────────────────────────────────────┘
                         ▲
                         │
                  ┌──────┴──────┐
                  │  Redis 7    │
                  │  (arq)      │
                  │ html_queue  │
                  │ ai_queue    │
                  └─────────────┘
```

### Пайплайн обработки

1. **Scraper** → собирает URL из поисковой выдачи, скачивает HTML-страницы, парсит через CSS-селекторы из `selectors.json`, сохраняет в `vacancies`, ставит задачу в `html_queue`.
2. **Transformer** (arq, `max_jobs=1`) → HTML→Markdown (MarkItDown), SHA-256 дедупликация, чанкинг (1200 символов, overlap=2), cosine similarity с резюме через rubert-tiny2, порог 0.70, ставит задачу в `ai_queue`.
3. **Analyzer** (arq, `max_jobs=15`) → отправляет Markdown в LLM (AsyncOpenAI), получает JSON (`score`, `pros`, `cons`, `cover_letter`), сохраняет в `vacancies.ai_analysis`.

### Статусы ссылок (`vacancy_links.status`)

| Значение     | Описание                                    |
|--------------|---------------------------------------------|
| `new`        | Ссылка собрана, ожидает обработки           |
| `parsed`     | HTML скачан и разобран, задача в transformer |
| `processed`  | LLM-анализ завершён                         |
| `rejected`   | Не прошёл фильтр similarity (< 0.70)        |
| `failed`     | Ошибка при скачивании/парсинге/LLM          |

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
│   └── src/
│       ├── config.py                # pydantic-settings
│       ├── database.py              # async engine + session maker
│       ├── models.py                # ORM-модели Vacancy, VacancyLink
│       ├── schemas.py               # DTO для arq
│       └── utils/
│           ├── logger.py            # Унифицированный логгер
│           └── crypto.py            # SHA-256
│
└── services/
    ├── scraper/                     # Сбор данных (Network I/O)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── selectors.json           # CSS-селекторы платформ
    │   └── src/
    │       ├── main.py              # Оркестратор
    │       ├── search.py            # Сбор URL
    │       └── pipeline.py          # Скачивание + парсинг
    │
    ├── transformer/                 # Фильтрация (CPU-bound)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── src/worker.py            # arq-воркер (max_jobs=1)
    │
    └── analyzer/                    # LLM-анализ (Network I/O)
        ├── Dockerfile
        ├── requirements.txt
        └── src/
            ├── worker.py            # arq-воркер (max_jobs=15)
            └── prompts.py           # Системный промпт
```

## Запуск

### 1. Подготовка окружения

```bash
cp .env.example .env
# Отредактируйте .env — укажите OPENAI_API_KEY, TARGET_RESUME и т.д.
```

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

### 3. Проверка состояния

```bash
# Логи
docker compose logs -f scraper
docker compose logs -f transformer
docker compose logs -f analyzer

# Статус контейнеров
docker compose ps
```

### 4. Подключение к БД

```bash
docker exec -it grindvac-postgres psql -U grindvac -d grindvac
```

## Конфигурация (.env)

| Переменная         | Описание                                         | По умолчанию                    |
|--------------------|--------------------------------------------------|---------------------------------|
| `POSTGRES_DB`      | Имя базы данных                                  | `grindvac`                      |
| `POSTGRES_USER`    | Пользователь БД                                  | `grindvac`                      |
| `POSTGRES_PASSWORD`| Пароль БД                                        | `grindvac_secret`               |
| `DATABASE_URL`     | SQLAlchemy async DSN                             | `postgresql+asyncpg://...`      |
| `REDIS_URL`        | Redis DSN                                        | `redis://localhost:6379`        |
| `OPENAI_API_KEY`   | Ключ OpenAI API                                  | *(обязательно)*                 |
| `OPENAI_BASE_URL`  | Базовый URL OpenAI-совместимого API              | `https://api.openai.com/v1`    |
| `OPENAI_MODEL_NAME`| Модель LLM                                       | `gpt-4o-mini`                   |
| `TARGET_RESUME`    | Текст резюме для семантического сравнения         | *(обязательно)*                 |

## Rate Limiting

Scraper ограничен **5 запросов за 6 секунд** : `await asyncio.sleep(random.uniform(1.0, 1.5))` перед каждым запросом. При ошибках скачивания — экспоненциальный backoff с джиттером (до 3 попыток).

## Дедупликация

- **По URL**: `UNIQUE(vacancy_links.url)` + `ON CONFLICT DO NOTHING`
- **По контенту**: SHA-256 от Markdown-текста вакансии → `UNIQUE(vacancies.content_hash)`. Дубликаты перепривязываются к существующей вакансии, ссылка получает статус `rejected`.

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
2. Добавьте slug-маппинг в `search.py` и `pipeline.py`: `_PLATFORM_SLUGS["example.com"] = "example"`
3. Пересоберите и запустите: `docker compose up -d --build`
