from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Bewerberzahlen", layout="wide")

page = st.navigation(
    [
        st.Page("src/app_pages/import_page.py", title="Import", icon=":material/upload_file:"),
        st.Page(
            "src/app_pages/data_management_page.py",
            title="Datenstandverwaltung",
            icon=":material/database:",
        ),
        st.Page("src/app_pages/dashboard_page.py", title="Dashboard", icon=":material/bar_chart:"),
    ],
    position="top",
)

page.run()
