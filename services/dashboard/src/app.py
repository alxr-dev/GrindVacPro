"""GrindVacPro dashboard — entrypoint."""

import streamlit as st

st.set_page_config(
    page_title="GrindVacPro Dashboard",
    page_icon="📊",
    layout="wide",
)

st.sidebar.title("📊 GrindVacPro")
st.sidebar.markdown("Мониторинг пайплайна вакансий")

overview = st.Page("pages/01_overview.py", title="Обзор", icon="📈")
analytics = st.Page("pages/02_analytics.py", title="Аналитика", icon="📉")
responses = st.Page("pages/03_responses.py", title="Отклики", icon="✉️")

pg = st.navigation([overview, analytics, responses])
pg.run()
