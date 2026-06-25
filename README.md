# GrindVacPro

**GrindVacPro** — асинхронная система автоматизации поиска вакансий. Собирает вакансии с платформ (hh.ru, career.habr.com), фильтрует по семантическому сходству с резюме через локальную ML-модель (rubert-tiny2), анализирует подходящие вакансии через LLM и отправляет карточки в Telegram.

---

## 🎯 Бизнес-ценность & Технические решения
*Кликните на интересующий пункт, чтобы раскрыть детали реализации.*

<details>
<summary><b>💰 1. Экономия на ИИ-инфраструктуре и оптимизация расходов на API</b></summary>

* **Бизнес-эффект:** Кормить коммерческие LLM (OpenAI/Anthropic) сырыми текстовыми массивами — это финансово больно для бизнеса. Данный модуль защищает бюджет компании, отсекая до 80% нерелевантного «мусора» и дубликатов до того, как они отправятся в платное API.
* **Как реализовано технически:** 
  * В БД PostgreSQL 18 развернуто расширение `pgvector` с HNSW-индексацией.
  * Локальная легковесная ML-модель `rubert-tiny2` на CPU вычисляет косинусное сходство (`cosine similarity`) между входящим текстом и целевой матрицей (порог `0.70`).
  * Контент предварительно нормализуется (HTML -> лаконичный Markdown через Microsoft MarkItDown) и дедуплицируется по SHA-256 хэшам. Если это дубль, он перепривязывается в СУБД, а задача в LLM-анализатор даже не создается.
</details>

<details>
<summary><b>🔄 2. Событийно-ориентированная архитектура и масштабируемость</b></summary>

* **Бизнес-эффект:** Система работает автономно в режиме 24/7 и легко расширяется. Если потребуется подключить новый источник данных, это делается за пару часов без остановки и пересборки остальных модулей.
* **Как реализовано технически:** 
  * Проект разделен на 4 независимых асинхронных микросервиса (Scraper, Transformer, Analyzer, Telegram Bot), изолированных в Docker-контейнерах.
  * Обмен данными и управление распределенными задачами организованы через очереди в Redis 7 с помощью легковесного воркера `arq`. 
  * Нагрузка четко разграничена: CPU-bound задачи (эмбеддинги) изолированы в одном воркере, а Network I/O (запросы к API и парсинг) параллельно обрабатываются в других.
</details>

<details>
<summary><b>🕷️ 3. Бесперебойный сбор данных и обход ограничений (Anti-Fraud Bypass)</b></summary>

* **Бизнес-эффект:** Гарантирует стабильный приток операционной информации без риска получить бан от внешних платформ, защищая компанию от затрат на капча-сервисы.
* **Как реализовано технически:** 
  * Модуль сбора данных написан с использованием библиотеки `curl_cffi`, которая имитирует TLS/JA3-отпечатки реального браузера (Chrome).
  * Реализован строгий асинхронный rate limiting (≤5 запросов за 6 секунд с рандомизацией пауз).
  * При возникновении сетевых ошибок или таймаутов срабатывает механизм повторных попыток (экспоненциальный backoff с джиттером).
</details>

<details>
<summary><b>📱 4. Интерфейс операционного контроля и stateless-модерация</b></summary>

* **Бизнес-эффект:** Оператор или менеджер получает структурированные ИИ-карточки прямо в мессенджер. Согласовать, отклонить или отправить сущность в работу можно в один клик. Идеально заменяет громоздкие и дорогие веб-панели управления.
* **Как реализовано технически:** 
  * Telegram-бот написан на `aiogram 3.x` и запущен в едином процессе с `arq`-воркером.
  * Архитектура кнопок полностью stateless — вся информация и идентификаторы действий упакованы в `callback_data` без использования классического FSM (Finite State Machine). Это снижает нагрузку на RAM и обеспечивает мгновенный отклик интерфейса.
</details>

---

## 🏗️ Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Scraper   │────>│  Transformer │────>│  Analyzer  │────>│  Telegram Bot    │     │     Dashboard    │
│ (curl_cffi) │     │ (arq, CPU×1) │     │(arq, IO×10)│     │(aiogram 3 + arq) │     │  (Streamlit)     │
└──────┬──────┘     └──────┬───────┘     └─────┬──────┘     └──────────────────┘     └──────────────────┘
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
4. **Telegram Bot** → единый процесс: `aiogram 3` (polling) + `arq` (воркер). Stateless inline-кнопки, двухэтапное подтверждение (карточка → действие → причина). По завершении сохраняет `status` (`accepted`/`declined`) и `notes` (причина) в БД.
5. **Dashboard** → Streamlit-приложение в контейнере. Читает данные из PostgreSQL (vacancies, vacancy_links), отображает KPI, графики и таблицы. Read-only, без изменения данных.

### Статусы ссылок (`vacancy_links.status`)

| Значение       | Описание                                                                      |
|----------------|-------------------------------------------------------------------------------|
| `new`          | Ссылка собрана, ожидает обработки                                             |
| `parsed`       | HTML скачан и разобран, задача в transformer                                  |
| `processed`    | LLM-анализ завершён; уведомление в Telegram отправлено, если score ≥ порог    |
| `rejected`     | Не прошёл фильтр similarity (`< SIMILARITY_THRESHOLD`)                        |
| `accepted`     | Пользователь принял вакансию через Telegram                                   |
| `declined`     | Пользователь отказался от вакансии через Telegram (причина в `Vacancy.notes`) |
| `failed`       | Ошибка при скачивании, парсинге или LLM-анализе                               |

## 🛠️ Стек

| Компонент       | Технология                              |
|-----------------|-----------------------------------------|
| Язык            | Python 3.12 (строгая асинхронность)     |
| HTTP-клиент     | `curl_cffi` (TLS/JA3 bypass)            |
| БД              | PostgreSQL 18 + pgvector                |
| Очереди         | Redis 7 + arq                           |
| ML (embedding)  | `SentenceTransformer('rubert-tiny2')`   |
| HTML→Markdown   | Microsoft MarkItDown                    |
| LLM             | OpenAI API (AsyncOpenAI)                |
| Telegram        | `aiogram 3.x`                           |
| Конфигурация    | pydantic-settings v2                    |
| Containerize    | Docker Compose                          |

## 📂 Структура проекта

```text
GrindVacPro/
├── docker-compose.yml
├── .env.example
├── .gitignore
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
    │   ├── resume.txt               # Символическая копия резюме для контейнера
    │   └── src/worker.py            # arq-воркер (max_jobs=1)
    │
    ├── analyzer/                    # LLM-анализ (Network I/O)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── resume.txt               # Символическая копия резюме для контейнера
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

    └── dashboard/                   # Визуализация (Streamlit)
        ├── Dockerfile
        ├── requirements.txt
        └── src/
            ├── app.py               # Entrypoint, multipage navigation
            └── pages/
                ├── 01_overview.py   # KPI, воронка, активность по дням
                ├── 02_analytics.py  # Score-гистограмма, платформы, топ вакансий
                └── 03_responses.py  # Причины принятия/отказа
```

## 🚀 Запуск

### 1. Подготовка окружения

```bash
cp .env.example .env
# Отредактируйте .env — укажите OPENAI_API_KEY, TELEGRAM_BOT_TOKEN и т.д.
```

Резюме хранится в файле `shared/resume.txt` и монтируется в контейнеры `transformer` и `analyzer` как read-only volume.

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
- `grindvac-dashboard` — веб-дашборд (`http://localhost:8501`)

### 3. Проверка состояния

```bash
# Логи
docker compose logs -f scraper
docker compose logs -f transformer
docker compose logs -f analyzer
docker compose logs -f telegram_bot
docker compose logs -f dashboard

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

## 📈 Направления для дальнейшего развития (Roadmap)

- **Миграции БД**: добавить Alembic для версионного управления схемой (сейчас `init.sql` отрабатывает только при первом создании базы)
- **Векторный поиск**: вынести семантический поиск по `vacancies.embedding` в отдельный сервис/задачу, чтобы искать похожие вакансии среди уже обработанных
- **Планировщик**: добавить периодический запуск scraper через `cron` / `arq` scheduler вместо ручного `docker compose up`
- **Ретраи и Dead Letter Queue**: для задач, которые упали с ошибкой 3+ раз — вынесение в отдельную очередь для ручной обработки
- **Тесты**: интеграционные pytest для каждого сервиса с моками (PostgreSQL в `testcontainers`, Redis в `pytest-asyncio`)
- **Линтинг**: добавить `ruff` / `mypy` в pre-commit и CI
- **Горячее обновление конфига**: перезапуск воркеров без пересборки контейнера при изменении `.env`
