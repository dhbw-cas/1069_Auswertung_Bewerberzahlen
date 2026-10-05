"""Independent, transactional PostgreSQL storage for final BEW and IMM counts."""

from __future__ import annotations

from typing import Any

import pandas as pd
from psycopg import Connection, sql

from .reference_import import (
    ReferenceCount,
    ReferenceMetric,
    validate_reference_counts,
)
from .storage import normalize_imported_by, semester_date_range

REFERENCE_TABLES: dict[ReferenceMetric, str] = {
    "BEW": "semester_application_totals",
    "IMM": "semester_enrollment_totals",
}
ReferenceKey = tuple[ReferenceMetric, str, str, str]


def reference_key(value: ReferenceCount) -> ReferenceKey:
    """Return a reference's independent metric/semester/department/program key."""
    return value.metric, value.semester, value.fachbereich, value.studiengang


def ensure_reference_schema(conn: Connection[Any]) -> None:
    """Create additive reference tables without touching application snapshots."""
    for table in REFERENCE_TABLES.values():
        conn.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    semester TEXT NOT NULL CHECK (length(trim(semester)) > 0),
                    fachbereich TEXT NOT NULL CHECK (length(trim(fachbereich)) > 0),
                    studiengang TEXT NOT NULL CHECK (length(trim(studiengang)) > 0),
                    anzahl INTEGER NOT NULL CHECK (anzahl >= 0),
                    filename TEXT NOT NULL,
                    sheet_name TEXT NOT NULL,
                    source_cell TEXT NOT NULL,
                    imported_by TEXT NOT NULL CHECK (length(trim(imported_by)) > 0),
                    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (semester, fachbereich, studiengang)
                )
                """
            ).format(sql.Identifier(table))
        )


def load_reference_counts(
    conn: Connection[Any], *, semesters: tuple[str, ...] = ()
) -> list[ReferenceCount]:
    """Load independently stored BEW/IMM counts, optionally limited to semesters."""
    for semester in semesters:
        semester_date_range(semester)
    ensure_reference_schema(conn)
    values: list[ReferenceCount] = []
    for metric, table in REFERENCE_TABLES.items():
        where = sql.SQL("WHERE semester = ANY(%s)") if semesters else sql.SQL("")
        records = conn.execute(
            sql.SQL(
                "SELECT semester, fachbereich, studiengang, anzahl, sheet_name, source_cell "
                "FROM {} {} ORDER BY semester, fachbereich, studiengang"
            ).format(sql.Identifier(table), where),
            (list(semesters),) if semesters else (),
        ).fetchall()
        values.extend(
            ReferenceCount(
                semester=str(row[0]),
                fachbereich=str(row[1]),
                studiengang=str(row[2]),
                count=int(row[3]),
                sheet_name=str(row[4]),
                source_cell=str(row[5]),
                metric=metric,
            )
            for row in records
        )
    return values


def load_final_year_rows(conn: Connection[Any], semester: str) -> pd.DataFrame:
    """Return report inputs with nullable counts; missing references are never zero."""
    records: dict[tuple[str, str], dict[str, object]] = {}
    columns = {"BEW": "BEW VJ final", "IMM": "IMM VJ final"}
    for value in load_reference_counts(conn, semesters=(semester,)):
        key = (value.fachbereich, value.studiengang)
        record = records.setdefault(
            key, {"fachbereich": value.fachbereich, "studiengang": value.studiengang}
        )
        record[columns[value.metric]] = value.count
    frame = pd.DataFrame(
        list(records.values()),
        columns=["fachbereich", "studiengang", "BEW VJ final", "IMM VJ final"],
    )
    for column in columns.values():
        frame[column] = pd.array(frame[column].tolist(), dtype="Int64")
    return frame


def import_reference_counts(
    conn: Connection[Any],
    values: list[ReferenceCount],
    *,
    filename: str,
    imported_by: str,
    replace_existing: bool = False,
    expected_existing: dict[ReferenceKey, int] | None = None,
) -> int:
    """Save selected values atomically; replacement needs explicit confirmation.

    If preview values are supplied, concurrent changes invalidate the preview.
    Omitted keys are retained, including when source cells were blank.
    """
    validate_reference_counts(values)
    author = normalize_imported_by(imported_by)
    if not filename.strip():
        raise ValueError("Quelldatei muss ausgefüllt sein.")
    with conn.transaction():
        ensure_reference_schema(conn)
        # A fixed lock order serializes previews-to-writes across both metric tables.
        conn.execute(
            sql.SQL("LOCK TABLE {}, {} IN SHARE ROW EXCLUSIVE MODE").format(
                *(sql.Identifier(table) for table in REFERENCE_TABLES.values())
            )
        )
        selected_keys = {reference_key(value) for value in values}
        existing = {
            reference_key(value): value.count
            for value in load_reference_counts(
                conn, semesters=tuple(sorted({value.semester for value in values}))
            )
            if reference_key(value) in selected_keys
        }
        if expected_existing is not None and existing != expected_existing:
            raise ValueError("Referenzzahlen wurden inzwischen geändert. Bitte Vorschau prüfen.")
        if existing and not replace_existing:
            raise ValueError(
                "Referenzzahlen vorhanden. Bitte das Ersetzen ausdrücklich bestätigen."
            )
        for value in values:
            table = REFERENCE_TABLES[value.metric]
            conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (
                        semester, fachbereich, studiengang, anzahl,
                        filename, sheet_name, source_cell, imported_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (semester, fachbereich, studiengang) DO UPDATE SET
                        anzahl = EXCLUDED.anzahl, filename = EXCLUDED.filename,
                        sheet_name = EXCLUDED.sheet_name, source_cell = EXCLUDED.source_cell,
                        imported_by = EXCLUDED.imported_by, imported_at = now()
                    """
                ).format(sql.Identifier(table)),
                (
                    value.semester,
                    value.fachbereich,
                    value.studiengang,
                    value.count,
                    filename,
                    value.sheet_name,
                    value.source_cell,
                    author,
                ),
            )
    return len(values)
