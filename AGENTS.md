# ГЛОБАЛЬНЫЕ ПРАВИЛА ПРОЕКТА

## 1. Стек и Стандарты Кода
- **Язык:** Python 3.12.10, строго асинхронный (`asyncio`).
- **Стиль:** 100% Type Hinting, KISS, SOLID, PEP8.
- **Инфраструктура:** PostgreSQL 18 + `pgvector`, Redis 7 + `arq`.
- **Конфигурация:** Реализовать в `shared/src/config.py` через `pydantic-settings` (автоподгрузка из `.env` с приведением типов).
- **База данных:** Все сессии СУБД открывать через `async with async_session_maker() as session:`. Создание таблиц только через `infra/postgres/init.sql`.

## 2. Структура Каталогов
```text
job_automator/
├── kilo.jsonc
├── infra/postgres/init.sql
├── shared/src/ (config.py, database.py, models.py, schemas.py, utils/)
└── services/
    ├── scraper/      # Сетевой сбор данных (curl_cffi) + selectors.json
    ├── transformer/  # CPU-bound обработка (arq, rubert-tiny2, markitdown)
    └── analyzer/     # ИИ-анализ (arq, openai API)