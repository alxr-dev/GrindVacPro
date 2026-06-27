"""GrindVacPro dashboard — entrypoint."""
import sys
from pathlib import Path

# Находим абсолютные пути к ключевым папкам
CURRENT_SRC = Path(__file__).resolve().parent      # /GrindVacPro/services/dashboard/src
DASHBOARD_ROOT = CURRENT_SRC.parent                # /GrindVacPro/services/dashboard
PROJECT_ROOT = DASHBOARD_ROOT.parent.parent        # /GrindVacPro

# Добавляем их в приоритет поиска Python
# Чтобы работал 'from shared...'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Чтобы на страницах работал 'from src.queries...'
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))


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
