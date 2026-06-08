from __future__ import annotations

import pandas as pd
import streamlit as st

from bewerberzahlen.app_config import get_database_url
from bewerberzahlen.storage import (
    DashboardFilters,
    connection_from_url,
    get_dashboard_filter_options,
    load_dashboard_rows,
)


def render_dashboard() -> None:
    st.title("Dashboard")
    st.caption(
        "Die Auswertung zaehlt Bewerbungszeilen ueber historische Snapshots. "
        "Dies ist keine eindeutige Personen- oder Bewerbungszaehlung."
    )
    database_url = get_database_url()
    if database_url is None:
        st.info("Keine Datenbankverbindung konfiguriert. Dashboard ist deaktiviert.")
        return

    try:
        with connection_from_url(database_url) as conn:
            options = get_dashboard_filter_options(conn)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Dashboard-Filter konnten nicht geladen werden: {exc}")
        return

    if options.min_snapshot_date is None or options.max_snapshot_date is None:
        st.info("Noch keine gespeicherten Importe vorhanden.")
        return

    filter_col1, filter_col2, filter_col3, filter_col4, filter_col5 = st.columns(5)
    with filter_col1:
        start_date = st.date_input("Von", value=options.min_snapshot_date, key="dashboard_start")
    with filter_col2:
        end_date = st.date_input("Bis", value=options.max_snapshot_date, key="dashboard_end")
    with filter_col3:
        selected_fachbereiche = st.multiselect(
            "Fachbereich", options=options.fachbereiche, key="dashboard_fachbereiche"
        )
    with filter_col4:
        selected_studiengaenge = st.multiselect(
            "Studiengang", options=options.studiengaenge, key="dashboard_studiengaenge"
        )
    with filter_col5:
        selected_statuses = st.multiselect(
            "Status", options=options.statuses, key="dashboard_statuses"
        )

    if start_date > end_date:
        st.error("Das Startdatum darf nicht nach dem Enddatum liegen.")
        return

    filters = DashboardFilters(
        start_date=start_date,
        end_date=end_date,
        fachbereiche=tuple(selected_fachbereiche),
        studiengaenge=tuple(selected_studiengaenge),
        statuses=tuple(selected_statuses),
    )

    try:
        with connection_from_url(database_url) as conn:
            dashboard_rows = load_dashboard_rows(conn, filters)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Dashboard-Daten konnten nicht geladen werden: {exc}")
        return

    if dashboard_rows.empty:
        st.info("Keine Daten fuer die gewaehlten Filter vorhanden.")
        return

    dashboard_rows = dashboard_rows.copy()
    dashboard_rows["snapshot_date"] = pd.to_datetime(dashboard_rows["snapshot_date"])

    latest_snapshot = dashboard_rows["snapshot_date"].max()
    latest_rows = dashboard_rows[dashboard_rows["snapshot_date"] == latest_snapshot]
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric(
        "Importe im Filter", f"{dashboard_rows['snapshot_date'].nunique():,}".replace(",", ".")
    )
    metric_col2.metric(
        "Bewerbungszeilen ueber Snapshots",
        f"{int(dashboard_rows['anzahl'].sum()):,}".replace(",", "."),
    )
    metric_col3.metric("Neuester Snapshot", latest_snapshot.strftime("%d.%m.%Y"))
    metric_col4.metric(
        "Zeilen im neuesten Snapshot", f"{int(latest_rows['anzahl'].sum()):,}".replace(",", ".")
    )

    st.subheader("Entwicklung ueber Snapshot-Datum")
    timeline = dashboard_rows.groupby("snapshot_date", as_index=True)["anzahl"].sum().sort_index()
    st.line_chart(timeline)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Statusentwicklung")
        status_over_time = dashboard_rows.pivot_table(
            index="snapshot_date", columns="status", values="anzahl", aggfunc="sum", fill_value=0
        ).sort_index()
        st.line_chart(status_over_time)
    with chart_col2:
        st.subheader("Fachbereichsentwicklung")
        fachbereich_over_time = dashboard_rows.pivot_table(
            index="snapshot_date",
            columns="fachbereich",
            values="anzahl",
            aggfunc="sum",
            fill_value=0,
        ).sort_index()
        st.line_chart(fachbereich_over_time)

    st.subheader("Top Studiengaenge")
    top_programs = dashboard_rows.groupby("studiengang", as_index=True)["anzahl"].sum().nlargest(15)
    st.bar_chart(top_programs)

    st.subheader("Aggregierte Detailtabelle")
    detail_rows = dashboard_rows.rename(
        columns={
            "snapshot_date": "Snapshot-Datum",
            "fachbereich": "Fachbereich",
            "studiengang": "Studiengang",
            "status": "Status",
            "anzahl": "Anzahl",
        }
    ).copy()
    detail_rows["Snapshot-Datum"] = detail_rows["Snapshot-Datum"].dt.strftime("%d.%m.%Y")
    st.dataframe(detail_rows, hide_index=True, use_container_width=True)


render_dashboard()
