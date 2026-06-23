# ИНСТРУКЦИЯ ДЛЯ СЕРВИСА ANALYZER (Network I/O)

## 1. Настройки Воркера
- Конфигурация `arq`: `max_jobs = 15` (высокий параллелизм сетевых запросов).
- Клиент: Асинхронный `AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)`.
- Модель: Динамическая, брать строго из переменной `settings.OPENAI_MODEL_NAME`.

## 2. Контракт ответа ИИ
- Системный промпт должен требовать от модели строго валидный JSON:
  ```json
  {
    "score": int, // 0-100 соответствие стека
    "pros": ["string"], // плюсы вакансии
    "cons": ["string"], // риски/минусы
    "cover_letter": "string" // адаптированное сопроводительное письмо
  }

  ```

## 3. Пост-обработка и интеграция с очередью (arq)
- **Запись в БД:** После успешного парсинга JSON-ответа от OpenAI, данные (`score`, `pros`, `cons`, `cover_letter`) должны быть сохранены в таблицу `vacancies` через асинхронную сессию SQLAlchemy.
- **Обновление ссылки:** Статус в `vacancy_links` меняется на `processed`.
- **Уведомление в Telegram:** После `session.commit()` сервис ставит задачу `send_vacancy_notification` в очередь `telegram_queue` через `arq create_pool`. В задачу передаётся `{"vacancy_id": vacancy_id}`.
- При ошибке отправки в очередь — логировать и продолжать (вакансия остаётся `processed`, уведомление можно повторить вручную).
