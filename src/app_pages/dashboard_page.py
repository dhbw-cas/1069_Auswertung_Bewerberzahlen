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
    ExistingImport,
    connection_from_url,
    dataset_label,
    get_dashboard_filter_options,
    load_dashboard_rows,
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

    if not options.datasets:
        st.info("Noch keine Datenbestände mit Berichtsdatum vorhanden.")
        return

    selector_col1, selector_col2 = st.columns(2)
    with selector_col1:
        selected_dataset = st.selectbox(
            "Datenbestand",
            options=options.datasets,
            format_func=dataset_label,
            key="dashboard_dataset",
        )
    with selector_col2:
        selected_report = st.selectbox(
            "Bericht",
            options=REPORT_DEFINITIONS,
            format_func=lambda report: report.label,
            key="dashboard_report",
        )
    if selected_report.id == BEWERBUNGSZAHLEN_WISE_REPORT_ID:
        _render_bewerbungszahlen_wise_report(database_url, options, selected_dataset)
    elif selected_report.id == OVERVIEW_REPORT_ID:
        _render_overview_dashboard(database_url, options, selected_dataset)
    else:
        st.error("Unbekannter Bericht.")


def _render_overview_dashboard(
    database_url: str, options: DashboardFilterOptions, selected_dataset: ExistingImport
) -> None:
    st.subheader(dataset_label(selected_dataset))
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_fachbereiche = st.multiselect(
            "Fachbereich", options=options.fachbereiche, key="dashboard_fachbereiche"
        )
    with filter_col2:
        selected_studiengaenge = st.multiselect(
            "Studiengang", options=options.studiengaenge, key="dashboard_studiengaenge"
        )
    with filter_col3:
        selected_statuses = st.multiselect(
            "Status", options=options.statuses, key="dashboard_statuses"
        )

    filters = DashboardFilters(
        batch_ids=(selected_dataset.id,),
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
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Datenbestand", f"#{selected_dataset.id}")
    metric_col2.metric(
        "Bewerbungszeilen",
        f"{int(dashboard_rows['anzahl'].sum()):,}".replace(",", "."),
    )
    metric_col3.metric(
        "Studiengänge", f"{dashboard_rows['studiengang'].nunique():,}".replace(",", ".")
    )
    metric_col4.metric(
        "Fachbereiche", f"{dashboard_rows['fachbereich'].nunique():,}".replace(",", ".")
    )

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Statusverteilung")
        status_counts = (
            dashboard_rows.groupby("status", as_index=True)["anzahl"].sum().sort_values()
        )
        st.bar_chart(status_counts)
    with chart_col2:
        st.subheader("Fachbereiche")
        fachbereich_counts = (
            dashboard_rows.groupby("fachbereich", as_index=True)["anzahl"].sum().sort_values()
        )
        st.bar_chart(fachbereich_counts)

    st.subheader("Top Studiengänge")
    top_programs = dashboard_rows.groupby("studiengang", as_index=True)["anzahl"].sum().nlargest(15)
    st.bar_chart(top_programs)

    st.subheader("Aggregierte Detailtabelle")
    detail_rows = dashboard_rows.rename(
        columns={
            "fachbereich": "Fachbereich",
            "studiengang": "Studiengang",
            "status": "Status",
            "anzahl": "Anzahl",
        }
    ).drop(columns=["dataset_id", "report_date"])
    st.dataframe(detail_rows, hide_index=True, use_container_width=True)


def _render_bewerbungszahlen_wise_report(
    database_url: str, options: DashboardFilterOptions, selected_dataset: ExistingImport
) -> None:
    st.subheader("Bewerbungszahlen WiSe")
    st.caption(
        "Der Bericht bildet den Excel-Bericht nach. Vorjahres-, Prognose- und Zielwertspalten "
        "sind vorbereitet und werden befüllt, sobald die Referenzdaten importiert werden."
    )
    st.markdown(f"**{dataset_label(selected_dataset)}**")

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        selected_fachbereiche = st.multiselect(
            "Fachbereich", options=options.fachbereiche, key="bewerbungszahlen_wise_fachbereiche"
        )
    with filter_col2:
        selected_studiengaenge = st.multiselect(
            "Studiengang", options=options.studiengaenge, key="bewerbungszahlen_wise_studiengaenge"
        )

    filters = DashboardFilters(
        batch_ids=(selected_dataset.id,),
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

    if selected_fachbereiche or selected_studiengaenge:
        report_rows = report_rows.replace({"Gesamtsumme": "Summe Auswahl"})

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


render_dashboard()
