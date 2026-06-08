from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Bewerberzahlen Dashboard", layout="wide")

page = st.navigation(
    [st.Page("app_pages/dashboard_page.py", title="Dashboard", icon=":material/bar_chart:")],
    position="top",
)

page.run()
