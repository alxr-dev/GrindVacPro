"""GrindVacPro dashboard — Overview page."""

import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from src.queries import get_kpi_overview, get_status_funnel, get_daily_stats

st.title("📈 Обзор пайплайна")

# Cache data for 60 seconds
@st.cache_data(ttl=60)
def load_data():
    return get_kpi_overview(), get_status_funnel(), get_daily_stats()

kpi, funnel, daily = load_data()

# KPI cards
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Всего ссылок", kpi["total_links"])
with col2:
    st.metric("Обработано", kpi["processed"])
with col3:
    st.metric("Отклонено (similarity)", kpi["rejected"])
with col4:
    st.metric("Принято", kpi["accepted"])
with col5:
    st.metric("Отказано", kpi["declined"])

st.divider()

col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Статусы ссылок")
    if funnel:
        df_funnel = pd.DataFrame(funnel)
        fig_funnel = px.bar(
            df_funnel,
            x="status",
            y="cnt",
            color="status",
            labels={"status": "Статус", "cnt": "Количество"},
        )
        fig_funnel.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig_funnel, use_container_width=True)
    else:
        st.info("Нет данных")

with col_b:
    st.subheader("Активность по дням")
    if daily:
        df_daily = pd.DataFrame(daily)
        df_daily["dt"] = pd.to_datetime(df_daily["dt"])
        fig_daily = px.line(
            df_daily,
            x="dt",
            y="cnt",
            markers=True,
            labels={"dt": "Дата", "cnt": "Ссылок"},
        )
        fig_daily.update_layout(height=350)
        st.plotly_chart(fig_daily, use_container_width=True)
    else:
        st.info("Нет данных за выбранный период")

st.caption(f"Обновлено: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
