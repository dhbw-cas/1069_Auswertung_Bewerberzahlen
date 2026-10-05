"""Admin preview and explicit, atomic import of final semester reference counts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pandas as pd
import streamlit as st

from bewerberzahlen.app_config import get_database_url
from bewerberzahlen.constants import FACHBEREICHE
from bewerberzahlen.mapping import ProgramResolver
from bewerberzahlen.reference_import import (
    ReferenceCount,
    ReferenceMetric,
    assign_reference_programs,
    read_reference_workbook_from_bytes,
)
from bewerberzahlen.reference_storage import (
    import_reference_counts,
    load_reference_counts,
    reference_key,
)
from bewerberzahlen.storage import connection_from_url, semester_label, semester_sort_key

MAX_UPLOAD_SIZE = 20 * 1024 * 1024
MAPPING_PATH = Path(__file__).resolve().parents[1] / "data/mapping/studiengaenge.json"
HISTORICAL_PROGRAM = "Eigenständiger historischer Studiengang"


@st.cache_data(show_spinner=False)
def _read_references(
    content: bytes, filename: str, metrics: tuple[ReferenceMetric, ...]
) -> list[ReferenceCount]:
    return read_reference_workbook_from_bytes(content, filename, metrics=metrics)


def render_reference_import_page() -> None:
    """Render the reference branch of the existing Altbestände admin page."""
    st.subheader("Finale BEW und IMM je Semester")
    st.caption(
        "BEW: Entwicklung Conversion BEW-IMMA. IMM: Entwicklung Imma je Studienjahr. "
        "Leere Zellen bleiben fehlend; eingetragene Nullen werden übernommen. "
        "Summen und Studienjahresspalten werden nicht importiert. Maximale Upload-Größe: 20 MB."
    )
    selected_metrics = st.multiselect(
        "Referenzarten", ["BEW", "IMM"], default=["BEW", "IMM"], key="reference_metrics"
    )
    uploader = st.file_uploader("Berichtsdatei hochladen", type=["xlsx"], key="reference_upload")
    if uploader is None:
        return
    if uploader.size > MAX_UPLOAD_SIZE:
        st.error("Datei ist größer als 20 MB und wird nicht verarbeitet.")
        return
    metrics = tuple(cast(ReferenceMetric, value) for value in selected_metrics)
    try:
        values = _read_references(uploader.getvalue(), uploader.name, metrics)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Semesterreferenzen konnten nicht gelesen werden: {exc}")
        return
    resolver = ProgramResolver.from_file(MAPPING_PATH)
    render_reference_preview(values, uploader.name, resolver)


def render_reference_preview(
    values: list[ReferenceCount], filename: str, resolver: ProgramResolver
) -> None:
    """Render assignments, stored-value comparison and the explicit save form."""
    semesters = sorted({value.semester for value in values}, key=semester_sort_key, reverse=True)
    selected = st.multiselect(
        "Semester importieren",
        semesters,
        default=semesters,
        format_func=semester_label,
        key="reference_semesters",
    )
    selected_values = [value for value in values if value.semester in selected]
    if not selected_values:
        st.info("Bitte mindestens ein Semester auswählen.")
        return
    assignments: dict[str, tuple[str, str]] = {}
    with st.expander("Studiengangszuordnungen prüfen", expanded=True):
        targets = ["Bitte auswählen", *resolver.program_names(), HISTORICAL_PROGRAM]
        for program in sorted({value.studiengang for value in selected_values}):
            canonical = resolver.canonical_name(program)
            target = st.selectbox(
                f"Zuordnung: {program}",
                targets,
                index=targets.index(canonical) if canonical in targets else 0,
                key=f"reference_program_{program}",
            )
            if target == HISTORICAL_PROGRAM:
                department = st.selectbox(
                    f"Fachbereich: {program}",
                    ["", *FACHBEREICHE],
                    key=f"reference_department_{program}",
                )
                if department:
                    assignments[program] = (program, department)
            elif target != "Bitte auswählen":
                resolved_department, _ = resolver.resolve(target)
                if resolved_department is not None:
                    assignments[program] = (target, resolved_department)
    try:
        assigned = assign_reference_programs(selected_values, assignments)
    except ValueError as exc:
        st.info(str(exc))
        return
    database_url = get_database_url()
    stored: list[ReferenceCount] = []
    if database_url is not None:
        try:
            with connection_from_url(database_url) as conn:
                stored = load_reference_counts(conn, semesters=tuple(selected))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Gespeicherte Referenzen konnten nicht geladen werden: {exc}")
            return
    keys = {reference_key(value) for value in assigned}
    existing = {
        reference_key(value): value.count for value in stored if reference_key(value) in keys
    }
    preview = [
        {
            "Semester": semester_label(value.semester),
            "Fachbereich": value.fachbereich,
            "Studiengang": value.studiengang,
            "Art": value.metric,
            "Neu": value.count,
            "Bisher": existing.get(reference_key(value)),
            "Quelle": f"{value.sheet_name}!{value.source_cell}",
        }
        for value in assigned
    ]
    preview_frame = pd.DataFrame(preview)
    preview_frame["Bisher"] = pd.array(preview_frame["Bisher"].tolist(), dtype="Int64")
    st.dataframe(preview_frame, hide_index=True, width="stretch")
    st.caption(
        "Es werden nur die angezeigten Werte gespeichert. Andere Referenzzahlen bleiben erhalten."
    )
    if database_url is None:
        st.info("Keine Datenbankverbindung konfiguriert. Speichern ist deaktiviert.")
        return
    # A new file, assignment or database value invalidates earlier confirmation widgets.
    fingerprint = hashlib.sha256(repr((filename, assigned, existing)).encode()).hexdigest()[:16]
    with st.form(f"reference_save_{fingerprint}"):
        imported_by = st.text_input("Importiert von *", key="reference_imported_by")
        confirmed = st.checkbox("Ich habe die Vorschau geprüft und möchte diese Werte speichern.")
        replace_existing = (
            st.checkbox("Ich bestätige das Ersetzen der angezeigten vorhandenen Referenzzahlen.")
            if existing
            else False
        )
        submitted = st.form_submit_button("Semesterreferenzen speichern", type="primary")
    if not submitted:
        return
    if not confirmed or (existing and not replace_existing):
        st.error("Bitte die Vorschau und gegebenenfalls das Ersetzen ausdrücklich bestätigen.")
        return
    try:
        with connection_from_url(database_url) as conn:
            count = import_reference_counts(
                conn,
                assigned,
                filename=filename,
                imported_by=imported_by,
                replace_existing=replace_existing,
                expected_existing=existing,
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Semesterreferenzen konnten nicht gespeichert werden: {exc}")
        return
    st.success(f"{count} Semesterreferenzen wurden gespeichert.")
