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