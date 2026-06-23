# ГЛОБАЛЬНЫЕ ПРАВИЛА ПРОЕКТА

## 1. Стек и Стандарты Кода
- **Язык:** Python 3.12.10, строго асинхронный (`asyncio`).
- **Стиль:** 100% Type Hinting, KISS, SOLID, PEP8.
- **Инфраструктура:** PostgreSQL 18 + `pgvector`, Redis 7 + `arq`.
- **Конфигурация:** Реализовать в `shared/src/config.py` через `pydantic-settings` (автоподгрузка из `.env` с приведением типов).
- **База данных:** Все сессии СУБД открывать через `async with async_session_maker() as session:`. Создание таблиц только через `infra/postgres/init.sql`.

## 2. Структура Каталогов и Пайплайн данных
```text
job_automator/
├── kilo.jsonc
├── infra/postgres/init.sql
├── shared/src/ (config.py, database.py, models.py, schemas.py, utils/)
└── services/
    ├── scraper/      # 1. Сетевой сбор ссылок и HTML (curl_cffi) + selectors.json
    ├── transformer/  # 2. Вычисление эмбеддингов (arq, rubert-tiny2, markitdown)
    ├── analyzer/     # 3. ИИ-анализ вакансий (arq, OpenAI API, генерация откликов)
    └── telegram_bot/ # 4. Доставка карточек, обработка кнопок отклика/отказа (aiogram 3)