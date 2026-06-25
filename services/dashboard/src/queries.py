"""GrindVacPro dashboard — database queries."""

from src.db import fetch_all, fetch_one


def get_kpi_overview() -> dict:
    """Overall pipeline metrics."""
    total_links = fetch_one(
        "SELECT COUNT(*) AS cnt FROM vacancy_links"
    )["cnt"]
    processed = fetch_one(
        "SELECT COUNT(*) AS cnt FROM vacancy_links WHERE status = 'processed'"
    )["cnt"]
    rejected = fetch_one(
        "SELECT COUNT(*) AS cnt FROM vacancy_links WHERE status = 'rejected'"
    )["cnt"]
    accepted = fetch_one(
        "SELECT COUNT(*) AS cnt FROM vacancy_links WHERE status = 'accepted'"
    )["cnt"]
    declined = fetch_one(
        "SELECT COUNT(*) AS cnt FROM vacancy_links WHERE status = 'declined'"
    )["cnt"]
    failed = fetch_one(
        "SELECT COUNT(*) AS cnt FROM vacancy_links WHERE status = 'failed'"
    )["cnt"]

    avg_score = fetch_one(
        "SELECT AVG(ai_score) AS avg_score FROM vacancies WHERE ai_score IS NOT NULL"
    )

    return {
        "total_links": total_links,
        "processed": processed,
        "rejected": rejected,
        "accepted": accepted,
        "declined": declined,
        "failed": failed,
        "avg_score": round(avg_score["avg_score"] or 0, 1),
    }


def get_status_funnel() -> list[dict]:
    """Count vacancies by status for funnel chart."""
    return fetch_all(
        """
        SELECT status, COUNT(*) AS cnt
        FROM vacancy_links
        GROUP BY status
        ORDER BY cnt DESC
        """
    )


def get_score_distribution() -> list[dict]:
    """Score distribution (buckets: 0-25, 26-50, 51-75, 76-100)."""
    return fetch_all(
        """
        SELECT
            CASE
                WHEN ai_score < 25 THEN '0-25'
                WHEN ai_score < 50 THEN '26-50'
                WHEN ai_score < 75 THEN '51-75'
                ELSE '76-100'
            END AS bucket,
            COUNT(*) AS cnt
        FROM vacancies
        WHERE ai_score IS NOT NULL
        GROUP BY bucket
        ORDER BY MIN(ai_score)
        """
    )


def get_platform_breakdown() -> list[dict]:
    """Vacancy count by platform."""
    return fetch_all(
        """
        SELECT platform, COUNT(*) AS cnt
        FROM vacancies
        GROUP BY platform
        ORDER BY cnt DESC
        """
    )


def get_scored_vacancies(limit: int = 100) -> list[dict]:
    """Recent vacancies with AI scores."""
    return fetch_all(
        """
        SELECT v.id, v.title, v.company_name, v.platform, v.ai_score,
               vl.status, vl.url, v.created_at
        FROM vacancies v
        JOIN vacancy_links vl ON vl.vacancy_id = v.id
        WHERE v.ai_score IS NOT NULL
        ORDER BY v.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )


def get_scored_vacancies_by_bucket(bucket: str, limit: int = 100) -> list[dict]:
    """Vacancies filtered by score bucket."""
    conditions = {
        "0-25": "v.ai_score < 25",
        "26-50": "v.ai_score >= 26 AND v.ai_score < 50",
        "51-75": "v.ai_score >= 51 AND v.ai_score < 75",
        "76-100": "v.ai_score >= 76",
    }
    where = conditions.get(bucket)
    if not where:
        return []
    return fetch_all(
        f"""
        SELECT v.id, v.title, v.company_name, v.platform, v.ai_score,
               vl.status, vl.url, v.created_at
        FROM vacancies v
        JOIN vacancy_links vl ON vl.vacancy_id = v.id
        WHERE v.ai_score IS NOT NULL AND {where}
        ORDER BY v.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )


def get_vacancy_details(vacancy_id: int) -> dict | None:
    """Full vacancy details including AI analysis."""
    return fetch_one(
        """
        SELECT v.id, v.title, v.company_name, v.platform, v.ai_score,
               v.ai_analysis, v.notes, v.created_at,
               vl.status, vl.url
        FROM vacancies v
        JOIN vacancy_links vl ON vl.vacancy_id = v.id
        WHERE v.id = :vid
        """,
        {"vid": vacancy_id},
    )


def get_response_stats() -> dict:
    """Accepted/declined statistics."""
    accepted_reasons = fetch_all(
        """
        SELECT notes AS reason, COUNT(*) AS cnt
        FROM vacancies
        WHERE notes IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM vacancy_links vl
              WHERE vl.vacancy_id = vacancies.id AND vl.status = 'accepted'
          )
        GROUP BY notes
        ORDER BY cnt DESC
        """
    )
    declined_reasons = fetch_all(
        """
        SELECT notes AS reason, COUNT(*) AS cnt
        FROM vacancies
        WHERE notes IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM vacancy_links vl
              WHERE vl.vacancy_id = vacancies.id AND vl.status = 'declined'
          )
        GROUP BY notes
        ORDER BY cnt DESC
        """
    )
    return {
        "accepted_reasons": accepted_reasons,
        "declined_reasons": declined_reasons,
    }


def get_daily_stats(days: int = 14) -> list[dict]:
    """Daily counts for trend chart."""
    return fetch_all(
        """
        SELECT DATE(created_at) AS dt, COUNT(*) AS cnt
        FROM vacancy_links
        WHERE created_at >= NOW() - INTERVAL ':days days'
        GROUP BY dt
        ORDER BY dt
        """,
        {"days": days},
    )
