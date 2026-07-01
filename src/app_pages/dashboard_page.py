from __future__ import annotations

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

from bewerberzahlen.app_config import get_database_url
from bewerberzahlen.reports import (
    BEWERBUNGSZAHLEN_WISE_REPORT_ID,
    OVERVIEW_REPORT_ID,
    PER_DATO_COLUMN,
    REPORT_DEFINITIONS,
    ROW_TYPE_COLUMN,
    build_bewerbungszahlen_wise_report,
)
from bewerberzahlen.storage import (
    DashboardFilterOptions,
    DashboardFilters,
    connection_from_url,
    get_dashboard_filter_options,
    load_dashboard_rows,
    semester_label,
    semester_sort_key,
)


def render_dashboard() -> None:
    st.title("Dashboard")
    st.caption(
        "Die Auswertung zählt Bewerbungszeilen über Semester-Datenstände. "
        "Dies ist keine eindeutige Personen- oder Bewerbungszählung."
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

    if not options.semesters:
        st.info("Noch keine gespeicherten Importe vorhanden.")
        return

    selected_report = st.selectbox(
        "Bericht",
        options=REPORT_DEFINITIONS,
        format_func=lambda report: report.label,
        key="dashboard_report",
    )
    if selected_report.id == BEWERBUNGSZAHLEN_WISE_REPORT_ID:
        _render_bewerbungszahlen_wise_report(database_url, options)
    elif selected_report.id == OVERVIEW_REPORT_ID:
        _render_overview_dashboard(database_url, options)
    else:
        st.error("Unbekannter Bericht.")


def _render_overview_dashboard(database_url: str, options: DashboardFilterOptions) -> None:
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        selected_semesters = st.multiselect(
            "Semester",
            options=options.semesters,
            format_func=semester_label,
            key="dashboard_semesters",
        )
    with filter_col2:
        selected_fachbereiche = st.multiselect(
            "Fachbereich", options=options.fachbereiche, key="dashboard_fachbereiche"
        )
    with filter_col3:
        selected_studiengaenge = st.multiselect(
            "Studiengang", options=options.studiengaenge, key="dashboard_studiengaenge"
        )
    with filter_col4:
        selected_statuses = st.multiselect(
            "Status", options=options.statuses, key="dashboard_statuses"
        )

    filters = DashboardFilters(
        semesters=tuple(selected_semesters),
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
        st.info("Keine Daten für die gewählten Filter vorhanden.")
        return

    dashboard_rows = dashboard_rows.copy()
    semester_order = sorted(dashboard_rows["semester"].unique(), key=semester_sort_key)
    dashboard_rows["semester_label"] = dashboard_rows["semester"].map(semester_label)

    latest_semester = max(dashboard_rows["semester"].unique(), key=semester_sort_key)
    latest_rows = dashboard_rows[dashboard_rows["semester"] == latest_semester]
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric(
        "Semester im Filter", f"{dashboard_rows['semester'].nunique():,}".replace(",", ".")
    )
    metric_col2.metric(
        "Bewerbungszeilen über Semester",
        f"{int(dashboard_rows['anzahl'].sum()):,}".replace(",", "."),
    )
    metric_col3.metric("Neuester Datenstand", semester_label(latest_semester))
    metric_col4.metric(
        "Zeilen im neuesten Datenstand", f"{int(latest_rows['anzahl'].sum()):,}".replace(",", ".")
    )

    st.subheader("Entwicklung über Semester")
    timeline = _ordered_semester_series(dashboard_rows, semester_order)
    st.line_chart(timeline)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Statusentwicklung")
        status_over_time = dashboard_rows.pivot_table(
            index="semester_label", columns="status", values="anzahl", aggfunc="sum", fill_value=0
        ).reindex([semester_label(semester) for semester in semester_order])
        st.line_chart(status_over_time)
    with chart_col2:
        st.subheader("Fachbereichsentwicklung")
        fachbereich_over_time = dashboard_rows.pivot_table(
            index="semester_label",
            columns="fachbereich",
            values="anzahl",
            aggfunc="sum",
            fill_value=0,
        ).reindex([semester_label(semester) for semester in semester_order])
        st.line_chart(fachbereich_over_time)

    st.subheader("Top Studiengänge")
    top_programs = dashboard_rows.groupby("studiengang", as_index=True)["anzahl"].sum().nlargest(15)
    st.bar_chart(top_programs)

    st.subheader("Aggregierte Detailtabelle")
    detail_rows = dashboard_rows.rename(
        columns={
            "semester_label": "Semester",
            "fachbereich": "Fachbereich",
            "studiengang": "Studiengang",
            "status": "Status",
            "anzahl": "Anzahl",
        }
    ).drop(columns=["semester"])
    st.dataframe(detail_rows, hide_index=True, use_container_width=True)


def _render_bewerbungszahlen_wise_report(
    database_url: str, options: DashboardFilterOptions
) -> None:
    st.subheader("Bewerbungszahlen WiSe")
    st.caption(
        "Der Bericht bildet den Excel-Bericht nach. Vorjahres-, Prognose- und Zielwertspalten "
        "sind vorbereitet und werden befüllt, sobald die Referenzdaten importiert werden."
    )

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_semester = st.selectbox(
            "Semester",
            options=options.semesters,
            format_func=semester_label,
            key="bewerbungszahlen_wise_semester",
        )
    with filter_col2:
        selected_fachbereiche = st.multiselect(
            "Fachbereich", options=options.fachbereiche, key="bewerbungszahlen_wise_fachbereiche"
        )
    with filter_col3:
        selected_studiengaenge = st.multiselect(
            "Studiengang", options=options.studiengaenge, key="bewerbungszahlen_wise_studiengaenge"
        )

    filters = DashboardFilters(
        semesters=(selected_semester,),
        fachbereiche=tuple(selected_fachbereiche),
        studiengaenge=tuple(selected_studiengaenge),
    )
    try:
        with connection_from_url(database_url) as conn:
            dashboard_rows = load_dashboard_rows(conn, filters)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Berichtsdaten konnten nicht geladen werden: {exc}")
        return

    report_rows = build_bewerbungszahlen_wise_report(dashboard_rows)
    if report_rows.empty:
        st.info("Keine Daten für den gewählten Bericht vorhanden.")
        return

    st.dataframe(
        _style_bewerbungszahlen_wise_report(report_rows),
        hide_index=True,
        use_container_width=True,
        height=720,
    )


def _style_bewerbungszahlen_wise_report(report_rows: pd.DataFrame) -> Styler:
    def style_row(row: pd.Series) -> list[str]:
        row_type = str(row.get(ROW_TYPE_COLUMN, ""))
        if row_type == "Gesamtsumme":
            return ["background-color: #bfbfbf; font-weight: 700;"] * len(row)
        if row_type == "Fachbereich":
            return ["background-color: #d9d9d9; font-weight: 700;"] * len(row)
        return [
            "background-color: #d9d9d9;" if column == PER_DATO_COLUMN else ""
            for column in row.index
        ]

    return report_rows.style.apply(style_row, axis=1).hide(axis="columns", subset=[ROW_TYPE_COLUMN])


def _ordered_semester_series(rows: pd.DataFrame, semester_order: list[str]) -> pd.Series:
    series = rows.groupby("semester_label", as_index=True)["anzahl"].sum()
    return series.reindex([semester_label(semester) for semester in semester_order])


render_dashboard()
