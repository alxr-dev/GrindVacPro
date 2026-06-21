# CONTEXT.md: Техническое описание архитектуры GrindVacPro

## 1. СТЕК ТЕХНОЛОГИЙ И КРИТИЧЕСКИЕ ЗАВИСИМОСТИ
- **Среда выполнения:** Python 3.12.10 (строгая асинхронность, `asyncio`).
- **Сетевой движок:** `curl_cffi` (`AsyncSession`) для нативного обхода TLS/JA3 защит (Cloudflare, противодействие анти-скрапинг системам).
- **База данных:** PostgreSQL 18 + расширение `pgvector` (нативное векторное хранилище и поиск).
- **Диспетчер задач:** `arq` (высокопроизводительные асинхронные очереди на базе Redis 7+).
- **Локальный ML-слой:** `SentenceTransformer('cointegrated/rubert-tiny2')` (размерность эмбеддинга: 312). Выполняет семантическую фильтрацию.
- **Обработка контента:** Microsoft `MarkItDown` (очистка сырого HTML-мусора в чистый Markdown).
- **ИИ-генерация:** `openai` (`AsyncOpenAI`) с поддержкой кастомных эндпоинтов.

---

## 2. АРХИТЕКТУРНАЯ СТРУКТУРА РЕПОЗИТОРИЯ

```text
GrindVacPro/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── README.md
├── AGENTS.md                     # Глобальные стандарты кодинга Kilo
├── CONTEXT.md                    # Этот файл (Архитектурный контекст)
│
├── infra/
│   └── postgres/
│       └── init.sql              # Базовый SQL-скрипт инициализации БД
│
├── shared/                       # Общее ядро системы
│   ├── requirements.txt
│   └── src/
│       ├── __init__.py
│       ├── config.py             # Валидация окружения через Pydantic Settings v2
│       ├── database.py           # Сессии SQLAlchemy и движок asyncpg
│       ├── models.py             # Декларативные ORM-модели SQLAlchemy 2.0
│       ├── schemas.py            # Pydantic DTO для валидации очередей arq
│       └── utils/
│           ├── __init__.py
│           ├── logger.py         # Унифицированный асинхронный логер
│           └── crypto.py         # Нахождение SHA-256 хэшей текста
│
└── services/                     # Микросервисный слой
    ├── scraper/                  # СЕРВИС 1: Сбор данных (Network I/O-bound)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── selectors.json        # Динамические CSS-селекторы (монтируются через Volume)
    │   └── src/
    │       ├── __init__.py
    │       ├── main.py           # Оркестратор search.py и pipeline.py
    │       ├── search.py         # Сборщик URL из поисковой выдачи
    │       └── pipeline.py       # Скачиватель и парсер HTML-страниц
    │
    ├── transformer/              # СЕРВИС 2: Фильтрация и эмбеддинги (CPU-bound)
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── src/
    │       ├── __init__.py
    │       └── worker.py         # arq-воркер (max_jobs=1), чанкинг, косинусное сходство
    │
    └── analyzer/                 # СЕРВИС 3: Интеграция с LLM (Network I/O-bound)
        ├── Dockerfile
        ├── requirements.txt
        └── src/
            ├── __init__.py
            ├── worker.py         # arq-воркер (max_jobs=15), генерация Cover Letter
            └── prompts.py        # Изолированные системные промпты

```

---

## 3. СХЕМА ИНИЦИАЛИЗАЦИИ СУБД (`infra/postgres/init.sql`)

> **Критическое ограничение:** Запрещено создавать таблицы методами Python в рантайме. База инициализируется строго через `init.sql`.

Вычисление семантического сходства в `pgvector` использует оператор косинусного расстояния `<=>`:


$$\text{Distance} = 1 - \text{Similarity}$$

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS vacancies (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(50) NOT NULL,           -- Системный слаг ('hh', 'habr')
    title VARCHAR(255) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    description_html TEXT NOT NULL,
    description_markdown TEXT,
    content_hash VARCHAR(64) UNIQUE NOT NULL, -- Защита от дублирования текста вакансии
    embedding vector(312),                   -- Эмбеддинг модели rubert-tiny2
    ai_score INT,
    ai_analysis JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vacancy_links (
    id SERIAL PRIMARY KEY,
    vacancy_id INT REFERENCES vacancies(id) ON DELETE CASCADE,
    url TEXT UNIQUE NOT NULL,                  -- Защита от повторного сбора ссылок
    platform VARCHAR(50) NOT NULL,           -- Источник ссылки
    status VARCHAR(20) DEFAULT 'new',          -- 'new', 'parsed', 'rejected', 'processed', 'failed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы для высоконагруженной выборки и векторного поиска
CREATE INDEX IF NOT EXISTS vacancies_embedding_idx ON vacancies USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS vacancies_platform_idx ON vacancies(platform);
CREATE INDEX IF NOT EXISTS vacancy_links_platform_idx ON vacancy_links(platform);

```

---

## 4. СЛУЖБА КОНФИГУРАЦИИ (`shared/src/config.py`)

Реализуется с помощью `pydantic-settings` (v2). Все типы приводятся автоматически в рантайме:

* `DATABASE_URL: str` (формат: `postgresql+asyncpg://...`)
* `REDIS_URL: str` (формат: `redis://...`)
* `OPENAI_API_KEY: str`
* `OPENAI_BASE_URL: str`
* `OPENAI_MODEL_NAME: str` (дефолт: `gpt-4o-mini`)
* `TARGET_RESUME: str` (текст резюме пользователя)

---

## 5. АЛГОРИТМ РАБОТЫ И СЕТЕВЫЕ ОГРАНИЧЕНИЯ

### Сетевое лимитирование (Rate Limiting)

Для всех модулей сервиса `scraper` действует ограничение: **не более 5 запросов за 6 секунд**.
Запрещено делать одновременные burst-запросы. Запросы должны плавно распределяться по таймлайну с внесением случайного шума (джиттера):
`await asyncio.sleep(random.uniform(1.0, 1.5))` перед каждым запросом.

### Шаг 1: Сбор ссылок (`search.py`)

1. Выполняет запросы к поисковой выдаче, используя `curl_cffi`.
2. Извлекает URL вакансий. Определяет платформу (`hh` или `habr`) через разбор домена с помощью `urllib.parse.urlparse`.
3. Делает пакетное сохранение: `INSERT INTO vacancy_links ... ON CONFLICT (url) DO NOTHING`. Дубликаты отсекаются на уровне БД.

### Шаг 2: Скачивание и первичный парсинг (`pipeline.py`)

1. Забирает из базы ссылки со статусом `new`.
2. Скачивает HTML-код страницы вакансии.
3. Читает файл конфигурации селекторов `/app/selectors.json`, динамически матчит домен вакансии с настройками парсера и вытаскивает значения полей `title`, `company_name`, `description_html`.
4. Создает временную запись в таблице `vacancies` (с временным `content_hash`), меняет статус ссылки на `parsed` и отправляет ID в очередь `html_queue` брокера `arq`.

### Шаг 3: Конвертация, Чанкинг и MaxSim-фильтрация (`worker.py` в transformer)

*Воркер запущен с ограничением `max_jobs = 1`.*

1. **Startup:** Один раз загружает модель `rubert-tiny2` в память и кодирует `settings.TARGET_RESUME` в эталонный вектор.
2. **Конвертация:** Переводит HTML вакансии в чистый Markdown через `MarkItDown`.
3. **Дедупликация текста:** Считает SHA-256 от Markdown. Если такой хэш уже существует в БД, текущая ссылка перепривязывается к существующей вакансии, а таска завершается.
4. **Накопительный Чанкинг:** Разбивает текст по `\n`. Накапливает строки в чанки максимальным размером в 1200 символов. На стыке чанков делает нахлест в `overlap_lines = 2` для сохранения контекста списков.
5. **Фильтрация:** Эмбедит каждый чанк. Считает косинусное сходство с резюме через `numpy`. Если `max_similarity < 0.70`, переводит ссылку в `rejected` и останавливает обработку. Если `>= 0.70`, сохраняет лучший вектор в `vacancies.embedding` и перенаправляет ID задачи в `ai_queue`.

### Шаг 4: Анализ и генерация сопроводительных писем (`worker.py` в analyzer)

*Воркер запущен со свободным параллелизмом `max_jobs = 15` (Network I/O).*

1. С помощью асинхронного клиента `AsyncOpenAI` отправляет Markdown-текст вакансии на обработку.
2. Системный промпт жестко требует структурированный JSON-ответ (поля `score`, `pros`, `cons`, `cover_letter`).
3. Записывает результат в JSONB поле `ai_analysis`, обновляет `ai_score` вакансии и переводит ссылку в финальный статус `processed`.

```