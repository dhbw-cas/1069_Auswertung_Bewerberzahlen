from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

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
from bewerberzahlen.storage import (
    DashboardFilters,
    DuplicateImportError,
    compute_content_hash,
    connection_from_url,
    delete_import_batch,
    extract_snapshot_date,
    get_dashboard_filter_options,
    import_cleaned_dataframe,
    is_delete_password_valid,
    list_import_batches,
    load_dashboard_rows,
)

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


def _get_config_value(name: str) -> str | None:
    env_value = os.environ.get(name)
    if env_value:
        return env_value
    try:
        secret_value = st.secrets.get(name)
    except (FileNotFoundError, KeyError, StreamlitSecretNotFoundError):
        return None
    if not secret_value:
        return None
    return str(secret_value)


def _get_database_url() -> str | None:
    return _get_config_value("DATABASE_URL")


def _render_import_history() -> None:
    st.header("Import-Historie")
    database_url = _get_database_url()
    if database_url is None:
        st.info("Keine Datenbankverbindung konfiguriert. Import-Historie ist deaktiviert.")
        return

    try:
        with connection_from_url(database_url) as conn:
            imports = list_import_batches(conn)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Import-Historie konnte nicht geladen werden: {exc}")
        return

    if not imports:
        st.info("Noch keine gespeicherten Importe vorhanden.")
        return

    import_rows = [
        {
            "ID": batch.id,
            "Snapshot-Datum": batch.snapshot_date.strftime("%d.%m.%Y"),
            "Datei": batch.filename,
            "Importiert von": batch.imported_by,
            "Importiert am": batch.created_at.strftime("%d.%m.%Y %H:%M"),
            "Zeilen": batch.row_count,
        }
        for batch in imports
    ]
    st.dataframe(pd.DataFrame(import_rows), hide_index=True, use_container_width=True)

    delete_password = _get_config_value("IMPORT_DELETE_PASSWORD")
    if delete_password is None:
        st.warning(
            "Löschen ist deaktiviert. Bitte IMPORT_DELETE_PASSWORD als Secret setzen, "
            "wenn Importe löschbar sein sollen."
        )
        return

    with st.expander("Import löschen"):
        labels_by_id = {
            batch.id: (
                f"#{batch.id} | {batch.snapshot_date:%d.%m.%Y} | "
                f"{batch.filename} | {batch.row_count} Zeilen"
            )
            for batch in imports
        }
        with st.form("delete_import_form"):
            selected_id = st.selectbox(
                "Zu löschender Import",
                options=list(labels_by_id.keys()),
                format_func=lambda batch_id: labels_by_id[int(batch_id)],
            )
            entered_password = st.text_input("Lösch-Passwort", type="password")
            confirmed = st.checkbox("Ich möchte diesen Import dauerhaft löschen.")
            submit_delete = st.form_submit_button("Import löschen")

        if submit_delete:
            if not confirmed:
                st.error("Bitte das Löschen explizit bestätigen.")
                return
            if not is_delete_password_valid(entered_password, delete_password):
                st.error("Lösch-Passwort ist falsch.")
                return
            try:
                with connection_from_url(database_url) as conn:
                    deleted = delete_import_batch(conn, int(selected_id))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Import konnte nicht gelöscht werden: {exc}")
                return
            if deleted:
                st.success("Import wurde gelöscht.")
                st.rerun()
            else:
                st.warning("Import wurde nicht gefunden oder war bereits gelöscht.")


def _render_dashboard() -> None:
    st.header("Dashboard")
    st.caption(
        "Die Auswertung zaehlt Bewerbungszeilen ueber historische Snapshots. "
        "Dies ist keine eindeutige Personen- oder Bewerbungszaehlung."
    )
    database_url = _get_database_url()
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

            st.divider()
            st.subheader("Bereinigte Daten importieren")
            content_hash = compute_content_hash(result.cleaned)
            st.caption(f"Inhaltsprüfung: `{content_hash[:12]}...`")

            guessed_snapshot_date = extract_snapshot_date(uploaded_name, default=date.today())
            with st.form("database_import_form"):
                imported_by = st.text_input("Importiert von *")
                snapshot_date = st.date_input(
                    "Snapshot-Datum",
                    value=guessed_snapshot_date or date.today(),
                    help="Aus dem Dateinamen vorbelegt, kann vor dem Speichern korrigiert werden.",
                )
                note = st.text_area("Notiz", placeholder="Optional")
                save_to_database = st.form_submit_button("In Datenbank speichern", type="primary")

            if save_to_database:
                database_url = _get_database_url()
                if database_url is None:
                    st.error(
                        "DATABASE_URL ist nicht gesetzt. Bitte als Umgebungsvariable oder "
                        "Streamlit Secret hinterlegen."
                    )
                else:
                    try:
                        with connection_from_url(database_url) as conn:
                            batch_id = import_cleaned_dataframe(
                                conn,
                                result.cleaned,
                                filename=uploaded_name,
                                snapshot_date=snapshot_date,
                                imported_by=imported_by,
                                note=note,
                            )
                    except DuplicateImportError as exc:
                        st.error(str(exc))
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Speichern fehlgeschlagen: {exc}")
                    else:
                        st.success(f"Import gespeichert (Batch-ID: {batch_id}).")

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

st.divider()
_render_import_history()
st.divider()
_render_dashboard()
