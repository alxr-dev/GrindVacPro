-- ══════════════════════════════════════════════════════════════
-- GrindVacPro — Инициализация базы данных
-- Расширение pgvector для векторного поиска (cosine distance)
-- ══════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Таблица вакансий ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vacancies (
    id            SERIAL PRIMARY KEY,
    platform      VARCHAR(50)  NOT NULL,
    title         VARCHAR(255) NOT NULL,
    company_name  VARCHAR(255) NOT NULL,
    description_html    TEXT   NOT NULL,
    description_markdown TEXT,
    content_hash  VARCHAR(64)  UNIQUE NOT NULL,
    embedding     vector(312),
    ai_score      INT,
    ai_analysis   JSONB,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ── Таблица ссылок на вакансии ─────────────────────────────────
CREATE TABLE IF NOT EXISTS vacancy_links (
    id         SERIAL PRIMARY KEY,
    vacancy_id INT          REFERENCES vacancies(id) ON DELETE CASCADE,
    url        TEXT         UNIQUE NOT NULL,
    platform   VARCHAR(50)  NOT NULL,
    status     VARCHAR(20)  DEFAULT 'new'
                 CHECK (status IN ('new', 'parsed', 'rejected', 'processed', 'failed')),
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ── Индексы для высоконагруженной выборки ──────────────────────

-- HNSW-индекс для быстрого векторного поиска (cosine distance)
CREATE INDEX IF NOT EXISTS vacancies_embedding_idx
    ON vacancies
    USING hnsw (embedding vector_cosine_ops);

-- B-tree индексы для фильтрации по платформе
CREATE INDEX IF NOT EXISTS vacancies_platform_idx
    ON vacancies (platform);

CREATE INDEX IF NOT EXISTS vacancy_links_platform_idx
    ON vacancy_links (platform);

-- Индекс для выборки необработанных ссылок
CREATE INDEX IF NOT EXISTS vacancy_links_status_idx
    ON vacancy_links (status);
