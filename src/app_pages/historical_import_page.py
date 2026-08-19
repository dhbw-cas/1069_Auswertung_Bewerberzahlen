from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from bewerberzahlen import FACHBEREICHE, Issue, PipelineConfig, ProgramResolver, process_dataframe
from bewerberzahlen.app_config import get_database_url
from bewerberzahlen.constants import PROGRAM_COLUMN, STATUS_COLUMN
from bewerberzahlen.historical_import import (
    HistoricalDataset,
    read_historical_workbook_from_bytes,
)
from bewerberzahlen.report import ProcessingResult
from bewerberzahlen.storage import connection_from_url, format_report_date, import_cleaned_dataframe

MAPPING_PATH = Path(__file__).resolve().parents[1] / "data" / "mapping" / "studiengaenge.json"
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
STATE_PREFIX = "historical_"


@st.cache_data(show_spinner=False)
def _load_mapping() -> ProgramResolver:
    return ProgramResolver.from_file(MAPPING_PATH)


@st.cache_data(show_spinner=False)
def _read_workbook(content: bytes, filename: str) -> list[HistoricalDataset]:
    return read_historical_workbook_from_bytes(content, filename)


def _clear_historical_state(*, include_upload: bool) -> None:
    for raw_key in list(st.session_state.keys()):
        key = str(raw_key)
        if not key.startswith(STATE_PREFIX):
            continue
        if not include_upload and key in {"historical_file_bytes", "historical_file_name"}:
            continue
        st.session_state.pop(key)


def _format_duplicate_option(row_number: int | None, dataframe: pd.DataFrame) -> str:
    if row_number is None:
        return "Bitte auswählen"

    index = row_number - 2
    if index < 0 or index >= len(dataframe):
        return f"Zeile {row_number}"

    row = dataframe.iloc[index]
    application_number = str(row.get("Bewerbungsnummer", "-")).strip() or "-"
    program_value = str(row.get(PROGRAM_COLUMN, "-")).strip() or "-"
    first_name = str(row.get("Formularfelder_Vorname", "-")).strip() or "-"
    last_name = str(row.get("Formularfelder_Name", "-")).strip() or "-"
    status_value = str(row.get(STATUS_COLUMN, "")).strip() or "-"
    start_value = str(row.get("BEW-Start", "")).strip() or "-"
    return (
        f"Zeile {row_number} | Bewerbungsnummer {application_number} | "
        f"Studiengang {program_value} | Name {first_name} {last_name} | "
        f"Status {status_value} | BEW-Start {start_value}"
    )


def _render_issues(dataset: HistoricalDataset, issues: list[Issue], title: str) -> None:
    if not issues:
        return
    with st.expander(
        f"{format_report_date(dataset.report_date)}: {title} ({len(issues)})",
        expanded=title == "Fehler",
    ):
        for issue in issues:
            rows = f" (Zeilen: {', '.join(map(str, issue.rows))})" if issue.rows else ""
            st.markdown(f"**{issue.message}**{rows}")


def render_historical_import_page() -> None:
    st.title("Altbestände importieren")
    st.markdown(
        "Liest alle Reiter nach dem Muster „Daten dd.mm.yyyy“, bereitet sie mit der regulären "
        "Importlogik auf und speichert jeden Stichtag als eigenen Datenbestand."
    )
    st.info("Pivot- und sonstige Reiter werden ignoriert. Maximale Upload-Größe: 20 MB.")

    with st.form("historical_upload_form"):
        uploader = st.file_uploader(
            "Historische XLSX-Datenbasis hochladen",
            type=["xlsx"],
            accept_multiple_files=False,
        )
        submit_upload = st.form_submit_button("Datenreiter einlesen", type="primary")

    if submit_upload:
        if uploader is None:
            st.error("Bitte eine XLSX-Datei auswählen.")
        elif uploader.size and uploader.size > MAX_UPLOAD_SIZE:
            st.error("Datei ist größer als 20 MB und wird nicht verarbeitet.")
        else:
            _clear_historical_state(include_upload=False)
            st.session_state["historical_file_bytes"] = uploader.getvalue()
            st.session_state["historical_file_name"] = uploader.name

    if st.button("Upload zurücksetzen"):
        _clear_historical_state(include_upload=True)
        st.rerun()

    uploaded_bytes = st.session_state.get("historical_file_bytes")
    uploaded_name = st.session_state.get("historical_file_name")
    if not isinstance(uploaded_bytes, (bytes, bytearray)) or not isinstance(uploaded_name, str):
        return

    _render_workbook(bytes(uploaded_bytes), uploaded_name)


def _render_workbook(uploaded_bytes: bytes, uploaded_name: str) -> None:
    try:
        datasets = _read_workbook(uploaded_bytes, uploaded_name)
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Historische Datenbasis konnte nicht gelesen werden: {exc}")
        return

    st.success(f"{len(datasets)} Datenreiter erkannt.")
    resolver = _load_mapping()
    manual_assignments = _render_unknown_program_assignments(datasets, resolver)
    duplicate_keep_rows = _render_duplicate_selections(
        datasets,
        resolver,
        manual_assignments,
    )

    results = {
        dataset.report_date: process_dataframe(
            dataset.dataframe,
            resolver,
            PipelineConfig(
                manual_assignments=manual_assignments or None,
                duplicate_keep_rows=duplicate_keep_rows[dataset.report_date] or None,
            ),
        )
        for dataset in datasets
    }
    _render_processing_summary(datasets, results)

    for dataset in datasets:
        result = results[dataset.report_date]
        _render_issues(dataset, result.errors, "Fehler")
        _render_issues(dataset, result.warnings, "Hinweise")

    if any(result.cleaned is None for result in results.values()):
        st.info(
            "Der Datenbankimport wird verfügbar, sobald alle Zuordnungen und "
            "Dublettenentscheidungen vollständig sind."
        )
        return

    _render_database_import(datasets, results, uploaded_name)


def _render_unknown_program_assignments(
    datasets: list[HistoricalDataset], resolver: ProgramResolver
) -> dict[str, str]:
    program_names: set[str] = set()
    for dataset in datasets:
        if PROGRAM_COLUMN not in dataset.dataframe:
            continue
        values = dataset.dataframe[PROGRAM_COLUMN].astype(str).str.strip()
        program_names.update(value for value in values if value)

    unknown_programs = resolver.unknown_programs(program_names)
    assignments: dict[str, str] = {}
    if not unknown_programs:
        st.success("Alle Studiengänge sind im Mapping hinterlegt.")
        return assignments

    st.warning("Unbekannte Studiengänge gefunden. Bitte einen Fachbereich zuordnen.")
    for program in sorted(unknown_programs):
        selection = st.selectbox(
            f'Fachbereich für "{program}"',
            options=[""] + FACHBEREICHE,
            key=f"historical_fachbereich_{program}",
        )
        if selection:
            assignments[program] = selection
    return assignments


def _render_duplicate_selections(
    datasets: list[HistoricalDataset],
    resolver: ProgramResolver,
    manual_assignments: dict[str, str],
) -> dict[date, set[int]]:
    selections: dict[date, set[int]] = {dataset.report_date: set() for dataset in datasets}
    previews = {
        dataset.report_date: process_dataframe(
            dataset.dataframe,
            resolver,
            PipelineConfig(manual_assignments=manual_assignments or None),
        )
        for dataset in datasets
    }

    duplicate_count = sum(len(result.duplicate_groups) for result in previews.values())
    if duplicate_count == 0:
        st.success("Keine Dubletten gefunden.")
        return selections

    st.warning(
        f"{duplicate_count} Dublettengruppen gefunden. Bitte pro Gruppe genau eine Zeile behalten."
    )
    for dataset in datasets:
        duplicate_groups = previews[dataset.report_date].duplicate_groups
        if not duplicate_groups:
            continue
        with st.expander(
            f"Dubletten vom {format_report_date(dataset.report_date)} "
            f"({len(duplicate_groups)} Gruppen)",
            expanded=True,
        ):
            for index, group_rows in enumerate(duplicate_groups, start=1):
                row_by_label = {
                    _format_duplicate_option(row_number, dataset.dataframe): row_number
                    for row_number in sorted(group_rows)
                }
                labels = ["Bitte auswählen", *row_by_label]
                selected_label = st.selectbox(
                    f"Dubletten-Gruppe {index}",
                    options=labels,
                    key=f"historical_duplicate_{dataset.report_date.isoformat()}_{index}",
                )
                if selected_label != "Bitte auswählen":
                    selections[dataset.report_date].add(row_by_label[selected_label])
    return selections


def _render_processing_summary(
    datasets: list[HistoricalDataset], results: dict[date, ProcessingResult]
) -> None:
    rows: list[dict[str, object]] = []
    for dataset in datasets:
        result = results[dataset.report_date]
        if result.errors:
            state = "Fehler"
        elif result.cleaned is None:
            state = "Auswahl erforderlich"
        else:
            state = "Bereit"
        rows.append(
            {
                "Stichtag": format_report_date(dataset.report_date),
                "Reiter": dataset.sheet_name,
                "Eingelesen": result.n_input,
                "Zu importieren": result.n_kept if result.cleaned is not None else "-",
                "Dubletten": result.n_duplicates,
                "Status": state,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_database_import(
    datasets: list[HistoricalDataset],
    results: dict[date, ProcessingResult],
    uploaded_name: str,
) -> None:
    st.divider()
    st.subheader("Altbestände in die Datenbank importieren")
    st.warning(
        "Vorhandene Datenbestände mit demselben Stichtag werden automatisch vollständig ersetzt. "
        "Jeder Stichtag wird einzeln gespeichert."
    )
    with st.form("historical_database_import_form"):
        imported_by = st.text_input("Importiert von *")
        note = st.text_area("Notiz", placeholder="Optional, gilt für alle Stichtage")
        save_to_database = st.form_submit_button(
            f"{len(datasets)} Stichtage importieren",
            type="primary",
        )

    if not save_to_database:
        return
    if not imported_by.strip():
        st.error("Bitte 'Importiert von' ausfüllen.")
        return

    database_url = get_database_url()
    if database_url is None:
        st.error(
            "DATABASE_URL ist nicht gesetzt. Bitte als Umgebungsvariable oder Streamlit Secret "
            "hinterlegen."
        )
        return

    successes: list[tuple[HistoricalDataset, int]] = []
    failures: list[tuple[HistoricalDataset, str]] = []
    try:
        with connection_from_url(database_url) as conn:
            for dataset in datasets:
                cleaned = results[dataset.report_date].cleaned
                if cleaned is None:
                    failures.append((dataset, "Datenbestand ist nicht vollständig aufbereitet."))
                    continue
                try:
                    batch_id = import_cleaned_dataframe(
                        conn,
                        cleaned,
                        filename=f"{uploaded_name} [{dataset.sheet_name}]",
                        report_date=dataset.report_date,
                        imported_by=imported_by,
                        note=note,
                        replace_existing=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append((dataset, str(exc)))
                else:
                    successes.append((dataset, batch_id))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Datenbankverbindung fehlgeschlagen: {exc}")
        return

    if successes:
        st.success(f"{len(successes)} von {len(datasets)} Stichtagen wurden gespeichert.")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Stichtag": format_report_date(dataset.report_date),
                        "Batch-ID": batch_id,
                    }
                    for dataset, batch_id in successes
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    for dataset, message in failures:
        st.error(f"{format_report_date(dataset.report_date)} wurde nicht gespeichert: {message}")


render_historical_import_page()
