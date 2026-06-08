from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

import pandas as pd
import pytest

from bewerberzahlen.constants import (
    ACCEPTED_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PROGRAM_COLUMN,
    PROGRAM_EXPORT_COLUMN,
    REJECTION_COLUMN,
    STATUS_COLUMN,
)
from bewerberzahlen.storage import (
    compute_content_hash,
    delete_import_batch,
    extract_snapshot_date,
    is_delete_password_valid,
    list_import_batches,
    normalize_imported_by,
)


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]] | None = None, rowcount: int = 0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _Transaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]] | None = None, delete_rowcount: int = 0):
        self.rows = rows or []
        self.delete_rowcount = delete_rowcount
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> _Cursor:
        self.executed.append((query, params))
        if "SELECT id, filename" in query:
            return _Cursor(rows=self.rows)
        if "DELETE FROM import_batches" in query:
            return _Cursor(rowcount=self.delete_rowcount)
        return _Cursor()

    def transaction(self) -> _Transaction:
        return _Transaction()


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Bewerbungsnummer": "1",
        STATUS_COLUMN: "Akzeptiert",
        "BEW-Start": "23.04.2026",
        ACCEPTED_COLUMN: "24.04.2026",
        "Gesamtstatus": "",
        REJECTION_COLUMN: "",
        NO_POTENTIAL_COLUMN: "0",
        FACHBEREICH_COLUMN: "Technik",
        PROGRAM_COLUMN: "Informatik",
        PROGRAM_EXPORT_COLUMN: "Informatik",
    }
    row.update(overrides)
    return row


def test_content_hash_ist_unabhaengig_von_zeilenreihenfolge() -> None:
    first = pd.DataFrame(
        [
            _row(Bewerbungsnummer="1"),
            _row(Bewerbungsnummer="2", **{PROGRAM_COLUMN: "Maschinenbau"}),
        ]
    )
    second = pd.DataFrame(
        [
            _row(Bewerbungsnummer="2", **{PROGRAM_COLUMN: "Maschinenbau"}),
            _row(Bewerbungsnummer="1"),
        ]
    )

    assert compute_content_hash(first) == compute_content_hash(second)


def test_content_hash_ist_unabhaengig_von_spaltenreihenfolge() -> None:
    first = pd.DataFrame([_row()])
    second = first[list(reversed(first.columns))]

    assert compute_content_hash(first) == compute_content_hash(second)


def test_content_hash_aendert_sich_bei_inhaltsaenderung() -> None:
    first = pd.DataFrame([_row()])
    second = pd.DataFrame([_row(**{STATUS_COLUMN: "Absage"})])

    assert compute_content_hash(first) != compute_content_hash(second)


def test_normalize_imported_by_trimmt_wert() -> None:
    assert normalize_imported_by("  Nico  ") == "Nico"


def test_normalize_imported_by_erfordert_wert() -> None:
    with pytest.raises(ValueError, match="Importiert von"):
        normalize_imported_by("   ")


def test_extract_snapshot_date_liest_deutsches_datum_aus_dateiname() -> None:
    assert extract_snapshot_date("Daten 15.03.2026.xlsx") == date(2026, 3, 15)


def test_extract_snapshot_date_liest_kompaktes_datum_aus_dateiname() -> None:
    assert extract_snapshot_date("Export_110526.csv") == date(2026, 5, 11)


def test_extract_snapshot_date_nutzt_default_ohne_datum() -> None:
    fallback = date(2026, 1, 2)

    assert extract_snapshot_date("export.csv", default=fallback) == fallback


def test_list_import_batches_mappt_db_rows() -> None:
    created_at = datetime(2026, 6, 8, 10, 30, tzinfo=UTC)
    conn = cast(
        Any,
        _FakeConnection(rows=[(7, "Export_110526.csv", date(2026, 5, 11), created_at, "Nico", 42)]),
    )

    batches = list_import_batches(conn)

    assert len(batches) == 1
    assert batches[0].id == 7
    assert batches[0].filename == "Export_110526.csv"
    assert batches[0].snapshot_date == date(2026, 5, 11)
    assert batches[0].created_at == created_at
    assert batches[0].imported_by == "Nico"
    assert batches[0].row_count == 42


def test_delete_import_batch_loescht_per_id() -> None:
    fake_conn = _FakeConnection(delete_rowcount=1)
    conn = cast(Any, fake_conn)

    assert delete_import_batch(conn, 7) is True
    assert ("DELETE FROM import_batches WHERE id = %s", (7,)) in fake_conn.executed


def test_delete_import_batch_lehnt_ungueltige_id_ab() -> None:
    with pytest.raises(ValueError, match="Import-ID"):
        delete_import_batch(cast(Any, _FakeConnection()), 0)


def test_is_delete_password_valid_vergleicht_passwort() -> None:
    assert is_delete_password_valid("geheim", "geheim") is True
    assert is_delete_password_valid("falsch", "geheim") is False
    assert is_delete_password_valid("geheim", None) is False
