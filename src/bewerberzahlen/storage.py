from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
from psycopg import Connection, connect
from psycopg.types.json import Jsonb

from .constants import (
    ACCEPTED_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PROGRAM_COLUMN,
    PROGRAM_EXPORT_COLUMN,
    REJECTION_COLUMN,
    STATUS_COLUMN,
)


@dataclass(frozen=True)
class ExistingImport:
    id: int
    filename: str
    report_date: date | None
    created_at: datetime
    imported_by: str
    row_count: int


@dataclass(frozen=True)
class DashboardFilters:
    batch_ids: tuple[int, ...] = ()
    semesters: tuple[str, ...] = ()
    fachbereiche: tuple[str, ...] = ()
    studiengaenge: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class DashboardFilterOptions:
    datasets: list[ExistingImport]
    fachbereiche: list[str]
    studiengaenge: list[str]
    statuses: list[str]


@dataclass(frozen=True)
class SemesterOption:
    key: str
    label: str
    starts_at: date
    ends_at: date


@dataclass(frozen=True)
class ReportDateOption:
    value: date
    label: str


class DatasetAlreadyExistsError(ValueError):
    def __init__(self, existing: ExistingImport):
        self.existing = existing
        label = dataset_label(existing)
        super().__init__(f"Für {label} existiert bereits ein Datenbestand.")


def build_semester_options(
    today: date | None = None, *, years_back: int = 6
) -> list[SemesterOption]:
    reference_year = (today or date.today()).year
    start_year = reference_year - years_back
    options: list[SemesterOption] = []
    for year in range(reference_year, start_year - 1, -1):
        winter_key = f"WS{year}_{(year + 1) % 100:02d}"
        summer_key = f"SS{year}"
        for key in (winter_key, summer_key):
            starts_at, ends_at = semester_date_range(key)
            options.append(
                SemesterOption(
                    key=key,
                    label=semester_label(key),
                    starts_at=starts_at,
                    ends_at=ends_at,
                )
            )
    return options


def build_report_date_options(
    today: date | None = None, *, option_count: int = 10
) -> list[ReportDateOption]:
    reference = today or date.today()
    candidates: list[date] = []
    year = reference.year
    month = reference.month

    while len(candidates) < option_count:
        last_day = monthrange(year, month)[1]
        for day in (last_day, 15):
            candidate = date(year, month, day)
            if candidate <= reference:
                candidates.append(candidate)
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return [
        ReportDateOption(value=report_date, label=format_report_date(report_date))
        for report_date in sorted(candidates, reverse=True)[:option_count]
    ]


def format_report_date(report_date: date) -> str:
    return report_date.strftime("%d.%m.%Y")


def dataset_label(dataset: ExistingImport) -> str:
    if dataset.report_date is None:
        return f"Legacy-Datenbestand #{dataset.id}"
    return f"Datenbestand vom {format_report_date(dataset.report_date)}"


def semester_label(semester: str) -> str:
    if match := re.fullmatch(r"SS(\d{4})", semester):
        return f"Sommersemester {match.group(1)}"
    if match := re.fullmatch(r"WS(\d{4})_(\d{2})", semester):
        return f"Wintersemester {match.group(1)}/{match.group(2)}"
    return semester


def semester_date_range(semester: str) -> tuple[date, date]:
    if match := re.fullmatch(r"SS(\d{4})", semester):
        year = int(match.group(1))
        return date(year - 1, 7, 1), date(year, 1, 15)
    if match := re.fullmatch(r"WS(\d{4})_(\d{2})", semester):
        year = int(match.group(1))
        expected_next_year = (year + 1) % 100
        if int(match.group(2)) != expected_next_year:
            raise ValueError(f"Ungültiges Semester: {semester}")
        return date(year, 1, 16), date(year, 6, 30)
    raise ValueError(f"Ungültiges Semester: {semester}")


def semester_from_snapshot_date(snapshot_date: date) -> str:
    if snapshot_date.month == 1 and snapshot_date.day <= 15:
        return f"SS{snapshot_date.year}"
    if snapshot_date.month >= 7:
        return f"SS{snapshot_date.year + 1}"
    return f"WS{snapshot_date.year}_{(snapshot_date.year + 1) % 100:02d}"


def semester_sort_key(semester: str) -> date:
    starts_at, _ = semester_date_range(semester)
    return starts_at


def connection_from_url(database_url: str) -> Connection[Any]:
    return connect(database_url)


def ensure_schema(conn: Connection[Any]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_batches (
            id BIGSERIAL PRIMARY KEY,
            filename TEXT NOT NULL,
            snapshot_date DATE,
            semester TEXT,
            report_date DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            imported_by TEXT NOT NULL CHECK (length(trim(imported_by)) > 0),
            row_count INTEGER NOT NULL CHECK (row_count >= 0),
            content_hash TEXT NOT NULL,
            note TEXT
        )
        """
    )
    conn.execute("ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS semester TEXT")
    conn.execute("ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS report_date DATE")
    conn.execute("ALTER TABLE import_batches ALTER COLUMN snapshot_date DROP NOT NULL")
    conn.execute("ALTER TABLE import_batches ALTER COLUMN semester DROP NOT NULL")
    _migrate_legacy_semesters(conn)
    conn.execute(
        "ALTER TABLE import_batches DROP CONSTRAINT IF EXISTS import_batches_content_hash_key"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id BIGSERIAL PRIMARY KEY,
            batch_id BIGINT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
            row_number INTEGER NOT NULL,
            bewerbungsnummer TEXT,
            status TEXT NOT NULL,
            bew_start DATE,
            fachbereich TEXT NOT NULL,
            studiengang TEXT NOT NULL,
            studiengang_export TEXT,
            accepted_at DATE,
            rejected_at DATE,
            no_potential BOOLEAN NOT NULL DEFAULT false,
            row_data JSONB NOT NULL,
            UNIQUE (batch_id, row_number)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_import_batches_semester ON import_batches (semester)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_import_batches_report_date_unique "
        "ON import_batches (report_date) WHERE report_date IS NOT NULL"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_batch_id ON applications (batch_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_applications_dimensions "
        "ON applications (fachbereich, studiengang, status)"
    )


def compute_content_hash(df: pd.DataFrame) -> str:
    columns = sorted(str(column) for column in df.columns)
    rows = [_normalized_record(row) for row in df.reindex(columns=columns).to_dict("records")]
    rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    payload = json.dumps(
        {"columns": columns, "rows": rows},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _migrate_legacy_semesters(conn: Connection[Any]) -> None:
    rows = conn.execute(
        """
        SELECT id, snapshot_date
        FROM import_batches
        WHERE semester IS NULL AND snapshot_date IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE import_batches SET semester = %s WHERE id = %s",
            (semester_from_snapshot_date(row[1]), int(row[0])),
        )


def normalize_imported_by(imported_by: str) -> str:
    normalized = imported_by.strip()
    if not normalized:
        raise ValueError("Bitte 'Importiert von' ausfüllen.")
    return normalized


def import_cleaned_dataframe(
    conn: Connection[Any],
    df: pd.DataFrame,
    *,
    filename: str,
    report_date: date,
    imported_by: str,
    note: str | None = None,
    replace_existing: bool = False,
) -> int:
    if df.empty:
        raise ValueError("Es können keine leeren Datenbestände importiert werden.")

    normalized_imported_by = normalize_imported_by(imported_by)
    content_hash = compute_content_hash(df)

    with conn.transaction():
        ensure_schema(conn)
        existing = find_dataset_by_report_date(conn, report_date)
        if existing is not None and not replace_existing:
            raise DatasetAlreadyExistsError(existing)
        if existing is not None:
            conn.execute("DELETE FROM import_batches WHERE id = %s", (existing.id,))

        row = conn.execute(
            """
            INSERT INTO import_batches (
                filename,
                snapshot_date,
                semester,
                report_date,
                imported_by,
                row_count,
                content_hash,
                note
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                filename,
                None,
                None,
                report_date,
                normalized_imported_by,
                len(df),
                content_hash,
                _normalize_optional_text(note),
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Import-Batch konnte nicht angelegt werden.")
        batch_id = int(row[0])

        for row_number, record in enumerate(_normalized_records(df), start=1):
            conn.execute(
                """
                INSERT INTO applications (
                    batch_id,
                    row_number,
                    bewerbungsnummer,
                    status,
                    bew_start,
                    fachbereich,
                    studiengang,
                    studiengang_export,
                    accepted_at,
                    rejected_at,
                    no_potential,
                    row_data
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    batch_id,
                    row_number,
                    _optional_text(record.get("Bewerbungsnummer")),
                    _required_text(record.get(STATUS_COLUMN), STATUS_COLUMN),
                    _parse_date(record.get("BEW-Start")),
                    _required_text(record.get(FACHBEREICH_COLUMN), FACHBEREICH_COLUMN),
                    _required_text(record.get(PROGRAM_COLUMN), PROGRAM_COLUMN),
                    _optional_text(record.get(PROGRAM_EXPORT_COLUMN)),
                    _parse_date(record.get(ACCEPTED_COLUMN)),
                    _parse_date(record.get(REJECTION_COLUMN)),
                    _parse_bool(record.get(NO_POTENTIAL_COLUMN)),
                    Jsonb(record),
                ),
            )

    return batch_id


def list_import_batches(conn: Connection[Any]) -> list[ExistingImport]:
    ensure_schema(conn)
    rows = conn.execute(
        """
        SELECT id, filename, report_date, created_at, imported_by, row_count
        FROM import_batches
        ORDER BY report_date DESC NULLS LAST, created_at DESC, id DESC
        """
    ).fetchall()
    return [_existing_import_from_row(row) for row in rows]


def list_datasets(conn: Connection[Any]) -> list[ExistingImport]:
    ensure_schema(conn)
    rows = conn.execute(
        """
        SELECT id, filename, report_date, created_at, imported_by, row_count
        FROM import_batches
        WHERE report_date IS NOT NULL
        ORDER BY report_date DESC, created_at DESC, id DESC
        """
    ).fetchall()
    return [_existing_import_from_row(row) for row in rows]


def find_dataset_by_report_date(conn: Connection[Any], report_date: date) -> ExistingImport | None:
    row = conn.execute(
        """
        SELECT id, filename, report_date, created_at, imported_by, row_count
        FROM import_batches
        WHERE report_date = %s
        """,
        (report_date,),
    ).fetchone()
    if row is None:
        return None
    return _existing_import_from_row(row)


def delete_import_batch(conn: Connection[Any], batch_id: int) -> bool:
    if batch_id <= 0:
        raise ValueError("Ungültige Import-ID.")

    with conn.transaction():
        ensure_schema(conn)
        cursor = conn.execute("DELETE FROM import_batches WHERE id = %s", (batch_id,))
    return cursor.rowcount == 1


def get_dashboard_filter_options(conn: Connection[Any]) -> DashboardFilterOptions:
    ensure_schema(conn)
    datasets = list_datasets(conn)
    fachbereiche = _fetch_distinct_values(conn, "fachbereich")
    studiengaenge = _fetch_distinct_values(conn, "studiengang")
    statuses = _fetch_distinct_values(conn, "status")
    return DashboardFilterOptions(
        datasets=datasets,
        fachbereiche=fachbereiche,
        studiengaenge=studiengaenge,
        statuses=statuses,
    )


def load_dashboard_rows(
    conn: Connection[Any], filters: DashboardFilters | None = None
) -> pd.DataFrame:
    ensure_schema(conn)
    where_sql, params = _build_dashboard_where(filters or DashboardFilters())
    rows = conn.execute(
        f"""
        SELECT
            b.id,
            b.report_date,
            a.fachbereich,
            a.studiengang,
            a.status,
            COUNT(*) AS anzahl
        FROM applications a
        JOIN import_batches b ON b.id = a.batch_id
        {where_sql}
        GROUP BY b.id, b.report_date, a.fachbereich, a.studiengang, a.status
        ORDER BY b.report_date, a.fachbereich, a.studiengang, a.status
        """,
        tuple(params),
    ).fetchall()
    records = [
        {
            "dataset_id": int(row[0]),
            "report_date": row[1],
            "fachbereich": str(row[2]),
            "studiengang": str(row[3]),
            "status": str(row[4]),
            "anzahl": int(row[5]),
        }
        for row in rows
    ]
    return pd.DataFrame(
        records,
        columns=["dataset_id", "report_date", "fachbereich", "studiengang", "status", "anzahl"],
    )


def is_delete_password_valid(entered_password: str, expected_password: str | None) -> bool:
    if expected_password is None or not expected_password:
        return False
    return hmac.compare_digest(entered_password, expected_password)


def _fetch_existing_semesters(conn: Connection[Any]) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT semester
        FROM import_batches
        WHERE semester IS NOT NULL AND length(trim(semester)) > 0
        """
    ).fetchall()
    semesters = [str(row[0]) for row in rows]
    return sorted(semesters, key=semester_sort_key, reverse=True)


def _fetch_distinct_values(conn: Connection[Any], column: str) -> list[str]:
    if column not in {"fachbereich", "studiengang", "status"}:
        raise ValueError(f"Ungültige Filterspalte: {column}")
    rows = conn.execute(
        f"""
        SELECT DISTINCT {column}
        FROM applications
        WHERE {column} IS NOT NULL AND length(trim({column})) > 0
        ORDER BY {column}
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _build_dashboard_where(filters: DashboardFilters) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    _add_int_in_filter(clauses, params, "b.id", filters.batch_ids)
    _add_in_filter(clauses, params, "b.semester", filters.semesters)
    _add_in_filter(clauses, params, "a.fachbereich", filters.fachbereiche)
    _add_in_filter(clauses, params, "a.studiengang", filters.studiengaenge)
    _add_in_filter(clauses, params, "a.status", filters.statuses)

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _add_int_in_filter(
    clauses: list[str], params: list[object], column: str, values: tuple[int, ...]
) -> None:
    normalized_values = tuple(value for value in values if value > 0)
    if not normalized_values:
        return
    placeholders = ", ".join(["%s"] * len(normalized_values))
    clauses.append(f"{column} IN ({placeholders})")
    params.extend(normalized_values)


def _add_in_filter(
    clauses: list[str], params: list[object], column: str, values: tuple[str, ...]
) -> None:
    normalized_values = tuple(value.strip() for value in values if value.strip())
    if not normalized_values:
        return
    placeholders = ", ".join(["%s"] * len(normalized_values))
    clauses.append(f"{column} IN ({placeholders})")
    params.extend(normalized_values)


def _existing_import_from_row(row: Any) -> ExistingImport:
    return ExistingImport(
        id=int(row[0]),
        filename=str(row[1]),
        report_date=row[2],
        created_at=row[3],
        imported_by=str(row[4]),
        row_count=int(row[5]),
    )


def _normalized_records(df: pd.DataFrame) -> list[dict[str, str]]:
    return [_normalized_record(row) for row in df.to_dict("records")]


def _normalized_record(row: dict[Any, Any]) -> dict[str, str]:
    return {str(key): _normalize_value(value) for key, value in row.items()}


def _normalize_value(value: object) -> str:
    if _is_missing_value(value):
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _is_missing_value(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return False


def _required_text(value: object, column: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"Pflichtfeld fehlt: {column}")
    return text


def _optional_text(value: object) -> str | None:
    text = _normalize_value(value)
    return text or None


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_date(value: object) -> date | None:
    text = _normalize_value(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Datum konnte nicht gelesen werden: {text}")


def _parse_bool(value: object) -> bool:
    text = _normalize_value(value).lower()
    return text in {"1", "true", "yes", "ja", "x"}
