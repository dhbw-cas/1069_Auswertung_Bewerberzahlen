from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from bewerberzahlen import (
    FACHBEREICHE,
    Issue,
    PipelineConfig,
    ProgramResolver,
    dataframe_to_excel_bytes,
    process_dataframe,
    read_import_csv_from_bytes,
)
from bewerberzahlen.constants import PROGRAM_COLUMN, STATUS_COLUMN

MAPPING_PATH = Path(__file__).resolve().parent / "data" / "mapping" / "studiengaenge.json"

st.set_page_config(page_title="Bewerberzahlen bereinigen", layout="wide")
st.title("Bewerberzahlen bereinigen")
st.markdown(
    "Bereinigt Bewerber-CSV-Dateien: Dubletten filtern, Status ableiten, Fachbereiche "
    "zuordnen und personenbezogene Spalten entfernen."
)


@st.cache_data(show_spinner=False)
def _load_mapping() -> ProgramResolver:
    return ProgramResolver.from_file(MAPPING_PATH)


def _render_issues(issues: list[Issue], title: str) -> None:
    if not issues:
        return
    expander = st.expander(f"{title} ({len(issues)})", expanded=True)
    with expander:
        for issue in issues:
            rows = f" (Zeilen: {', '.join(map(str, issue.rows))})" if issue.rows else ""
            expander.markdown(f"**{issue.message}**{rows}")


def _clear_dynamic_state() -> None:
    for raw_key in list(st.session_state.keys()):
        key = str(raw_key)
        if key.startswith("fachbereich_") or key.startswith("duplicate_keep_"):
            st.session_state.pop(key)


def _format_duplicate_option(row_number: int, df_with_rows: pd.DataFrame) -> str:
    match = df_with_rows[df_with_rows["__row_number"] == row_number]
    if match.empty:
        return f"Zeile {row_number}"

    row = match.iloc[0]
    application_number = str(row.get("Bewerbungsnummer", "-")).strip() or "-"
    status_value = str(row.get(STATUS_COLUMN, "")).strip() or "-"
    start_value = str(row.get("BEW-Start", "")).strip() or "-"
    return (
        f"Zeile {row_number} | Bewerbungsnummer {application_number} | "
        f"Status {status_value} | BEW-Start {start_value}"
    )


st.info("Maximale Upload-Größe: 20 MB", icon="ℹ️")

with st.form("bereinigung_form"):
    uploader = st.file_uploader("CSV-Datei hochladen", type=["csv"], accept_multiple_files=False)
    submit = st.form_submit_button("Bereinigen", type="primary")

if submit:
    if not uploader:
        st.error("Bitte eine CSV-Datei auswählen.")
    elif uploader.size and uploader.size > 20 * 1024 * 1024:
        st.error("Datei ist größer als 20 MB und wird nicht verarbeitet.")
    else:
        _clear_dynamic_state()
        st.session_state["uploaded_file_bytes"] = uploader.getvalue()
        st.session_state["uploaded_file_name"] = uploader.name

if st.button("Upload zurücksetzen"):
    _clear_dynamic_state()
    st.session_state.pop("uploaded_file_bytes", None)
    st.session_state.pop("uploaded_file_name", None)
    st.rerun()

uploaded_bytes = st.session_state.get("uploaded_file_bytes")
uploaded_name = st.session_state.get("uploaded_file_name")

if isinstance(uploaded_bytes, (bytes, bytearray)) and isinstance(uploaded_name, str):
    try:
        df = read_import_csv_from_bytes(bytes(uploaded_bytes))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Konnte Datei nicht lesen: {exc}")
    else:
        resolver = _load_mapping()
        df_with_rows = df.copy()
        df_with_rows["__row_number"] = range(2, len(df_with_rows) + 2)

        manual_assignments: dict[str, str] = {}
        if PROGRAM_COLUMN in df.columns:
            program_names = df[PROGRAM_COLUMN].astype(str).str.strip().dropna().unique()
            unknown_programs = resolver.unknown_programs(program_names, manual_assignments=None)
        else:
            unknown_programs = set()

        if unknown_programs:
            st.warning(
                "Unbekannte Studiengänge gefunden. Bitte Fachbereich zuordnen, damit die Datei "
                "bereinigt werden kann.",
                icon="⚠️",
            )
            for program in sorted(unknown_programs):
                fachbereich_selection = st.selectbox(
                    f'Fachbereich für "{program}"',
                    options=[""] + FACHBEREICHE,
                    key=f"fachbereich_{program}",
                )
                if fachbereich_selection:
                    manual_assignments[program.strip()] = fachbereich_selection
        else:
            st.success("Alle Studiengänge sind im Mapping hinterlegt.")

        preview_result = process_dataframe(
            df,
            resolver,
            PipelineConfig(
                manual_assignments=manual_assignments or None,
                duplicate_keep_rows=None,
            ),
        )

        duplicate_keep_rows: set[int] = set()
        if preview_result.duplicate_groups:
            st.warning(
                "Dubletten gefunden. Bitte pro Gruppe genau einen Eintrag auswählen, "
                "der behalten werden soll.",
                icon="⚠️",
            )
            for idx, group_rows in enumerate(preview_result.duplicate_groups, start=1):
                options = sorted(group_rows)
                row_by_label: dict[str, int] = {}
                labels = ["Bitte auswählen"]
                for row_number in options:
                    label = _format_duplicate_option(row_number, df_with_rows)
                    row_by_label[label] = row_number
                    labels.append(label)

                selected_label = st.selectbox(
                    f"Dubletten-Gruppe {idx}",
                    options=labels,
                    key=f"duplicate_keep_{idx}",
                )
                if selected_label != "Bitte auswählen":
                    duplicate_keep_rows.add(row_by_label[selected_label])

        result = process_dataframe(
            df,
            resolver,
            PipelineConfig(
                manual_assignments=manual_assignments or None,
                duplicate_keep_rows=duplicate_keep_rows or None,
            ),
        )

        _render_issues(result.errors, "Fehler")
        _render_issues(result.warnings, "Hinweise")

        if result.errors:
            st.error(
                "Verarbeitung fehlgeschlagen. "
                f"Eingelesen: {result.n_input}, "
                f"unbekannte Studiengänge: {result.n_unknown_program}",
            )
        elif result.cleaned is None and result.duplicate_groups:
            st.warning(
                "Bereinigung pausiert: Bitte Dubletten-Auswahl vollständig ausfüllen.",
                icon="⚠️",
            )
        else:
            st.success(
                "Bereit: "
                f"Eingelesen: {result.n_input}, behalten: {result.n_kept}, "
                f"Dubletten: {result.n_duplicates}, fehlender Studiengang ignoriert: "
                f"{result.n_missing_program}, unbekannte Studiengänge: "
                f"{result.n_unknown_program}",
            )

        if result.cleaned is None:
            if result.errors:
                st.error("Bereinigung nicht möglich, bitte Fehler beheben.")
        else:
            today = date.today().strftime("%Y%m%d")
            base_name = Path(uploaded_name).stem
            cleaned_bytes = dataframe_to_excel_bytes(result.cleaned)
            st.download_button(
                "Bereinigte Datei herunterladen",
                data=cleaned_bytes,
                file_name=f"cleaned_{base_name}_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )

        if not result.duplicates.empty:
            today = date.today().strftime("%Y%m%d")
            base_name = Path(uploaded_name).stem
            duplicates_bytes = dataframe_to_excel_bytes(result.duplicates)
            st.download_button(
                "Dubletten-Liste herunterladen",
                data=duplicates_bytes,
                file_name=f"duplicates_{base_name}_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
