"""GrindVacPro dashboard — Analytics page."""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.queries import (
    get_score_distribution,
    get_platform_breakdown,
    get_scored_vacancies,
    get_scored_vacancies_by_bucket,
    get_vacancy_details,
)

st.title("📉 Аналитика")

tab1, tab2, tab3 = st.tabs(["Score", "Платформы", "Топ вакансий"])

with tab1:
    st.subheader("Распределение AI-score")

    @st.cache_data(ttl=120)
    def load_scores():
        return get_score_distribution()

    scores = load_scores()
    if scores:
        df_scores = pd.DataFrame(scores)
        # Ensure correct bucket order
        bucket_order = ["0-25", "26-50", "51-75", "76-100"]
        df_scores["bucket"] = pd.Categorical(
            df_scores["bucket"], categories=bucket_order, ordered=True
        )
        df_scores = df_scores.sort_values("bucket")

        fig = px.bar(
            df_scores,
            x="bucket",
            y="cnt",
            color="bucket",
            labels={"bucket": "Score", "cnt": "Количество"},
        )
        fig.update_layout(showlegend=False, height=400)
        
        # Click on a bar to see vacancies in that bucket
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun")
        
        selected_bucket = None
        if event and event.selection and event.selection.get("points"):
            selected_bucket = event.selection["points"][0]["x"]
        
        if selected_bucket:
            st.caption(f"Выбран диапазон: **{selected_bucket}**")
            bucket_vacancies = get_scored_vacancies_by_bucket(selected_bucket, limit=50)
            if bucket_vacancies:
                df_bucket = pd.DataFrame(bucket_vacancies)
                df_bucket = df_bucket.sort_values("ai_score", ascending=False)
                display_cols = ["title", "company_name", "platform", "ai_score", "status", "url"]
                df_display = df_bucket[display_cols].copy()
                df_display.columns = [
                    "Название", "Компания", "Платформа", "Score", "Статус", "URL"
                ]
                
                event_bucket = st.dataframe(
                    df_display,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "URL": st.column_config.LinkColumn("Ссылка", display_text="Открыть"),
                        "Score": st.column_config.ProgressColumn(
                            "Score", min_value=0, max_value=100, format="%d"
                        ),
                    },
                    on_select="rerun",
                    selection_mode="single-row",
                )
                
                selected_rows = event_bucket.selection.rows if event_bucket and event_bucket.selection else []
                if selected_rows:
                    idx = selected_rows[0]
                    vacancy = bucket_vacancies[idx]
                    details = get_vacancy_details(vacancy["id"])
                    if details:
                        with st.expander("📋 Подробности вакансии", expanded=True):
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write(f"**Название:** {details['title']}")
                                st.write(f"**Компания:** {details['company_name']}")
                                st.write(f"**Платформа:** {details['platform']}")
                                st.write(f"**Score:** {details['ai_score']}")
                                st.write(f"**Статус:** {details['status']}")
                            with col2:
                                st.write(f"**Ссылка:** [Открыть]({details['url']})")
                                st.write(f"**Заметка:** {details['notes'] or '—'}")
                            
                            ai = details.get("ai_analysis") or {}
                            if ai:
                                st.divider()
                                st.subheader("AI-анализ")
                                if ai.get("pros"):
                                    st.write("**Плюсы:**")
                                    for p in ai["pros"]:
                                        st.write(f"✅ {p}")
                                if ai.get("cons"):
                                    st.write("**Минусы:**")
                                    for c in ai["cons"]:
                                        st.write(f"⚠️ {c}")
                                if ai.get("cover_letter"):
                                    st.write("**Сопроводительное письмо:**")
                                    st.code(ai["cover_letter"], language=None)
            else:
                st.info("Нет вакансий в этом диапазоне")

        # Histogram via plotly
        st.subheader("Гистограмма score")
        scored = get_scored_vacancies(limit=500)
        if scored:
            df_scored = pd.DataFrame(scored)
            fig_hist = px.histogram(
                df_scored,
                x="ai_score",
                nbins=20,
                labels={"ai_score": "AI Score", "count": "Количество"},
            )
            fig_hist.update_layout(height=350)
            st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.info("Нет данных по score")

with tab2:
    st.subheader("Вакансии по платформам")

    @st.cache_data(ttl=120)
    def load_platforms():
        return get_platform_breakdown()

    platforms = load_platforms()
    if platforms:
        df_plat = pd.DataFrame(platforms)
        fig_pie = px.pie(
            df_plat,
            names="platform",
            values="cnt",
            hole=0.4,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(height=500)
        st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("Таблица")
        st.dataframe(df_plat, use_container_width=True, hide_index=True)
    else:
        st.info("Нет данных по платформам")

with tab3:
    st.subheader("Топ вакансий по score")

    @st.cache_data(ttl=60)
    def load_top():
        return get_scored_vacancies(limit=50)

    top = load_top()
    if top:
        df_top = pd.DataFrame(top)
        df_top = df_top.sort_values("ai_score", ascending=False)

        display_cols = ["title", "company_name", "platform", "ai_score", "status", "url"]
        df_display = df_top[display_cols].copy()
        df_display.columns = [
            "Название", "Компания", "Платформа", "Score", "Статус", "URL"
        ]
        
        event_top = st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("Ссылка", display_text="Открыть"),
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                ),
            },
            on_select="rerun",
            selection_mode="single-row",
        )
        
        selected_rows = event_top.selection.rows if event_top and event_top.selection else []
        if selected_rows:
            idx = selected_rows[0]
            vacancy = top[idx]
            details = get_vacancy_details(vacancy["id"])
            if details:
                with st.expander("📋 Подробности вакансии", expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Название:** {details['title']}")
                        st.write(f"**Компания:** {details['company_name']}")
                        st.write(f"**Платформа:** {details['platform']}")
                        st.write(f"**Score:** {details['ai_score']}")
                        st.write(f"**Статус:** {details['status']}")
                    with col2:
                        st.write(f"**Ссылка:** [Открыть]({details['url']})")
                        st.write(f"**Заметка:** {details['notes'] or '—'}")
                    
                    ai = details.get("ai_analysis") or {}
                    if ai:
                        st.divider()
                        st.subheader("AI-анализ")
                        if ai.get("pros"):
                            st.write("**Плюсы:**")
                            for p in ai["pros"]:
                                st.write(f"✅ {p}")
                        if ai.get("cons"):
                            st.write("**Минусы:**")
                            for c in ai["cons"]:
                                st.write(f"⚠️ {c}")
                        if ai.get("cover_letter"):
                            st.write("**Сопроводительное письмо:**")
                            st.code(ai["cover_letter"], language=None)
    else:
        st.info("Нет обработанных вакансий")
