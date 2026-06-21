# GrindVacPro — План реализации

## Milestone 0 — Скелет и инфраструктура
- [x] 0.1 `docker-compose.yml` — сервисы postgres, redis, scraper, transformer, analyzer
- [x] 0.2 `infra/postgres/init.sql` — таблицы `vacancies`, `vacancy_links` + HNSW-индексы (VARCHAR+CHECK для статусов)
- [x] 0.3 `.env.example` — шаблон всех переменных окружения
- [x] 0.4 `.gitignore`
- [x] 0.5 `shared/requirements.txt` — общие зависимости

## Milestone 1 — Shared-ядро (`shared/src/`)
- [x] 1.1 `config.py` — pydantic-settings v2 (DATABASE_URL, REDIS_URL, OPENAI_*, TARGET_RESUME)
- [x] 1.2 `database.py` — asyncpg + async_session_maker (SQLAlchemy 2.0 async)
- [x] 1.3 `models.py` — ORM-модели Vacancy и VacancyLink
- [x] 1.4 `schemas.py` — Pydantic DTO для очередей arq
- [x] 1.5 `utils/logger.py` — единый асинхронный логгер
- [x] 1.6 `utils/crypto.py` — sha256() для дедупликации

## Milestone 2 — Сервис Scraper (`services/scraper/`)
- [x] 2.1 `requirements.txt`
- [x] 2.2 `Dockerfile`
- [x] 2.3 `src/main.py` — CLI-оркестратор
- [x] 2.4 `src/search.py` — сбор URL через curl_cffi, rate-limit
- [x] 2.5 `src/pipeline.py` — скачивание + парсинг через selectors.json
- [x] 2.6 Проверка `selectors.json`

## Milestone 3 — Сервис Transformer (`services/transformer/`)
- [x] 3.1 `requirements.txt`
- [x] 3.2 `Dockerfile`
- [x] 3.3 `src/worker.py` — arq-воркер (max_jobs=1), rubert-tiny2, MarkItDown, чанкинг, cosine similarity

## Milestone 4 — Сервис Analyzer (`services/analyzer/`)
- [x] 4.1 `requirements.txt`
- [x] 4.2 `Dockerfile`
- [x] 4.3 `src/prompts.py` — системный промпт с JSON-схемой
- [x] 4.4 `src/worker.py` — arq-воркер (max_jobs=15), AsyncOpenAI

## Milestone 5 — Интеграция и деплой
- [x] 5.1 E2E-прогон через docker-compose
- [x] 5.2 Обработка ошибок (retry, dead-letter, failed)
- [x] 5.3 README.md

## Ключевые решения
- Статусы ссылок — VARCHAR(20) + CHECK, не ENUM (расширяемость)
- Эмбеддинг rubert-tiny2 — размерность 312
- Порог similarity для фильтрации — 0.70
- Rate limit scraper — 5 req / 6 сек, sleep(random.uniform(1.0, 1.5))
- Чанкинг: макс. 1200 символов, overlap 2 строки
