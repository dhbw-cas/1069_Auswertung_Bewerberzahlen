from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from bewerberzahlen.app_config import get_database_url
from bewerberzahlen.mapping import ProgramResolver
from bewerberzahlen.reference_storage import load_final_year_rows
from bewerberzahlen.report_table import render_bewerbungszahlen_wise_table
from bewerberzahlen.reports import (
    BEWERBUNGSZAHLEN_WISE_REPORT_ID,
    OVERVIEW_REPORT_ID,
    PROGRAM_COLUMN,
    REPORT_DEFINITIONS,
    build_bewerbungszahlen_wise_report,
    forecast_reference_warnings,
    previous_year_report_date,
)
from bewerberzahlen.storage import (
    DashboardFilterOptions,
    DashboardFilters,
    ExistingImport,
    connection_from_url,
    dataset_label,
    find_dataset_by_report_date,
    get_dashboard_filter_options,
    load_dashboard_rows,
    semester_label,
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
    st.dataframe(detail_rows, hide_index=True, width="stretch")


def _render_bewerbungszahlen_wise_report(
    database_url: str, options: DashboardFilterOptions, selected_dataset: ExistingImport
) -> None:
    st.subheader("Bewerbungszahlen WiSe")
    st.caption(
        "Der Bericht bildet den Excel-Bericht nach. Vorjahreswerte werden über den "
        "exakt gleichen Stichtag im Vorjahr ermittelt. Alle Bewerbungen entsprechen "
        "„per dato“: akzeptiert + offen, ohne „Kein Potential“ und „Absagen“."
    )
    st.markdown(f"**{dataset_label(selected_dataset)}**")

    default_year = (selected_dataset.report_date or date.today()).year
    target_year = int(
        st.number_input(
            "Zielsemester: Startjahr des Wintersemesters",
            min_value=1901,
            max_value=9998,
            value=default_year,
            key=f"wise_target_year_{selected_dataset.id}",
        )
    )
    target_semester = f"WS{target_year}_{(target_year + 1) % 100:02d}"
    reference_semester = f"WS{target_year - 1}_{target_year % 100:02d}"
    st.caption(
        f"Zielsemester: {semester_label(target_semester)}. "
        f"Finale Referenzzahlen: {semester_label(reference_semester)}."
    )

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
    previous_date = (
        previous_year_report_date(selected_dataset.report_date)
        if selected_dataset.report_date is not None
        else None
    )
    previous_dataset: ExistingImport | None = None
    previous_year_rows: pd.DataFrame | None = None
    try:
        with connection_from_url(database_url) as conn:
            dashboard_rows = load_dashboard_rows(conn, filters)
            final_year_rows = load_final_year_rows(conn, reference_semester)
            if previous_date is not None:
                previous_dataset = find_dataset_by_report_date(conn, previous_date)
            if previous_dataset is not None:
                previous_year_rows = load_dashboard_rows(
                    conn,
                    DashboardFilters(
                        batch_ids=(previous_dataset.id,),
                        fachbereiche=tuple(selected_fachbereiche),
                        studiengaenge=tuple(selected_studiengaenge),
                    ),
                )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Berichtsdaten konnten nicht geladen werden: {exc}")
        return

    if previous_date is not None and previous_dataset is None:
        st.info(
            f"Für den Vorjahresstichtag {previous_date:%d.%m.%Y} ist kein Datenbestand "
            "vorhanden. Vorjahres- und Deltafelder werden als „-“ angezeigt."
        )
    elif previous_dataset is not None:
        st.caption(f"Vorjahresvergleich: {dataset_label(previous_dataset)}")

    resolver = ProgramResolver.from_file(
        Path(__file__).resolve().parents[1] / "data/mapping/studiengaenge.json"
    )
    try:
        report_rows = build_bewerbungszahlen_wise_report(
            dashboard_rows,
            previous_year_rows,
            previous_year_final_rows=final_year_rows,
            program_resolver=resolver,
        )
    except ValueError as exc:
        st.error(f"Prognose konnte nicht berechnet werden: {exc}")
        return
    if report_rows.empty:
        st.info("Keine Daten für den gewählten Bericht vorhanden.")
        return

    if selected_fachbereiche or selected_studiengaenge:
        report_rows[PROGRAM_COLUMN] = report_rows[PROGRAM_COLUMN].replace(
            {"Gesamtsumme": "Summe Auswahl"}
        )

    warnings = forecast_reference_warnings(report_rows)
    if warnings:
        st.warning(
            "Referenzbasis prüfen: "
            + " ".join(warnings)
            + " Summen verwenden die verfügbaren Finalzahlen und alle ausgewählten "
            "Bewerbungen. Bei fehlenden Finalzahlen beruhen sie auf einer Teilbasis "
            "und können verzerrt sein."
        )
    st.caption(
        "Prognose BEW = aktuelle BEW ÷ (BEW am Vorjahresstichtag ÷ finale BEW). "
        "Prognose IMM = Prognose BEW × (finale IMM ÷ finale BEW)."
    )

    st.html(
        render_bewerbungszahlen_wise_table(report_rows, dark_mode=st.context.theme.type == "dark"),
        width="stretch",
        unsafe_allow_javascript=False,
    )


render_dashboard()
