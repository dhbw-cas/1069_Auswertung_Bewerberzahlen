from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
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
    snapshot_date: date
    created_at: datetime
    imported_by: str
    row_count: int


class DuplicateImportError(ValueError):
    def __init__(self, existing: ExistingImport):
        self.existing = existing
        super().__init__(
            "Dieser bereinigte Datenbestand wurde bereits importiert: "
            f"{existing.filename} am {existing.created_at:%d.%m.%Y %H:%M}."
        )


def connection_from_url(database_url: str) -> Connection[Any]:
    return connect(database_url)


def ensure_schema(conn: Connection[Any]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_batches (
            id BIGSERIAL PRIMARY KEY,
            filename TEXT NOT NULL,
            snapshot_date DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            imported_by TEXT NOT NULL CHECK (length(trim(imported_by)) > 0),
            row_count INTEGER NOT NULL CHECK (row_count >= 0),
            content_hash TEXT NOT NULL UNIQUE,
            note TEXT
        )
        """
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
        "CREATE INDEX IF NOT EXISTS idx_import_batches_snapshot_date "
        "ON import_batches (snapshot_date)"
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


def normalize_imported_by(imported_by: str) -> str:
    normalized = imported_by.strip()
    if not normalized:
        raise ValueError("Bitte 'Importiert von' ausfüllen.")
    return normalized


def extract_snapshot_date(filename: str, default: date | None = None) -> date | None:
    separated_match = re.search(r"(\d{1,2})[._-](\d{1,2})[._-](\d{4})", filename)
    if separated_match:
        day, month, year = (int(part) for part in separated_match.groups())
        return date(year, month, day)

    compact_match = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", filename)
    if compact_match:
        day, month, year_short = (int(part) for part in compact_match.groups())
        return date(2000 + year_short, month, day)

    return default


def import_cleaned_dataframe(
    conn: Connection[Any],
    df: pd.DataFrame,
    *,
    filename: str,
    snapshot_date: date,
    imported_by: str,
    note: str | None = None,
) -> int:
    if df.empty:
        raise ValueError("Es können keine leeren Datenbestände importiert werden.")

    normalized_imported_by = normalize_imported_by(imported_by)
    content_hash = compute_content_hash(df)

    with conn.transaction():
        ensure_schema(conn)
        existing = find_import_by_hash(conn, content_hash)
        if existing is not None:
            raise DuplicateImportError(existing)

        row = conn.execute(
            """
            INSERT INTO import_batches (
                filename, snapshot_date, imported_by, row_count, content_hash, note
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                filename,
                snapshot_date,
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
        SELECT id, filename, snapshot_date, created_at, imported_by, row_count
        FROM import_batches
        ORDER BY snapshot_date DESC, created_at DESC, id DESC
        """
    ).fetchall()
    return [_existing_import_from_row(row) for row in rows]


def delete_import_batch(conn: Connection[Any], batch_id: int) -> bool:
    if batch_id <= 0:
        raise ValueError("Ungültige Import-ID.")

    with conn.transaction():
        ensure_schema(conn)
        cursor = conn.execute("DELETE FROM import_batches WHERE id = %s", (batch_id,))
    return cursor.rowcount == 1


def find_import_by_hash(conn: Connection[Any], content_hash: str) -> ExistingImport | None:
    row = conn.execute(
        """
        SELECT id, filename, snapshot_date, created_at, imported_by, row_count
        FROM import_batches
        WHERE content_hash = %s
        """,
        (content_hash,),
    ).fetchone()
    if row is None:
        return None
    return _existing_import_from_row(row)


def is_delete_password_valid(entered_password: str, expected_password: str | None) -> bool:
    if expected_password is None or not expected_password:
        return False
    return hmac.compare_digest(entered_password, expected_password)


def _existing_import_from_row(row: Any) -> ExistingImport:
    return ExistingImport(
        id=int(row[0]),
        filename=str(row[1]),
        snapshot_date=row[2],
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
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Datum konnte nicht gelesen werden: {text}")


def _parse_bool(value: object) -> bool:
    text = _normalize_value(value).lower()
    return text in {"1", "true", "yes", "ja", "x"}
