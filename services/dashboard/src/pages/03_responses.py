"""GrindVacPro dashboard — Responses page."""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.queries import get_response_stats

st.title("✉️ Отклики")

@st.cache_data(ttl=120)
def load_stats():
    return get_response_stats()

stats = load_stats()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Причины отказа")
    declined = stats.get("declined_reasons", [])
    if declined:
        df_declined = pd.DataFrame(declined)
        if df_declined["reason"].notna().any():
            fig_declined = px.pie(
                df_declined,
                names="reason",
                values="cnt",
                hole=0.3,
            )
            fig_declined.update_traces(textposition="inside", textinfo="percent+label")
            fig_declined.update_layout(height=400)
            st.plotly_chart(fig_declined, use_container_width=True)
        else:
            st.info("Нет данных")
    else:
        st.info("Нет отказов")

with col2:
    st.subheader("Причины отклика")
    accepted = stats.get("accepted_reasons", [])
    if accepted:
        df_accepted = pd.DataFrame(accepted)
        if df_accepted["reason"].notna().any():
            fig_accepted = px.pie(
                df_accepted,
                names="reason",
                values="cnt",
                hole=0.3,
            )
            fig_accepted.update_traces(textposition="inside", textinfo="percent+label")
            fig_accepted.update_layout(height=400)
            st.plotly_chart(fig_accepted, use_container_width=True)
        else:
            st.info("Нет данных")
    else:
        st.info("Нет откликов")

st.divider()

st.subheader("Детализация")
if declined or accepted:
    rows = []
    for r in declined:
        rows.append({"action": "❌ Отказ", "reason": r["reason"], "count": r["cnt"]})
    for r in accepted:
        rows.append({"action": "✔️ Отклик", "reason": r["reason"], "count": r["cnt"]})

    if rows:
        df_detail = pd.DataFrame(rows)
        df_detail = df_detail.sort_values(["action", "count"], ascending=[True, False])
        st.dataframe(
            df_detail,
            use_container_width=True,
            hide_index=True,
            column_config={
                "action": st.column_config.TextColumn("Действие", width="small"),
                "reason": st.column_config.TextColumn("Причина", width="medium"),
                "count": st.column_config.NumberColumn("Кол-во", width="small"),
            },
        )
else:
    st.info("Пока нет ни одного решения через Telegram")
