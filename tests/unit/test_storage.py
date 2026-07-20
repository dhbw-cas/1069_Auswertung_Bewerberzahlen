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
    DashboardFilters,
    DatasetAlreadyExistsError,
    build_report_date_options,
    build_semester_options,
    compute_content_hash,
    dataset_label,
    delete_import_batch,
    get_dashboard_filter_options,
    import_cleaned_dataframe,
    is_delete_password_valid,
    list_import_batches,
    load_dashboard_rows,
    normalize_imported_by,
    semester_date_range,
    semester_from_snapshot_date,
    semester_label,
)


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]] | None = None, rowcount: int = 0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


class _Transaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _FakeConnection:
    def __init__(
        self,
        rows: list[tuple[object, ...]] | None = None,
        delete_rowcount: int = 0,
        dashboard_rows: list[tuple[object, ...]] | None = None,
        existing_semesters: list[str] | None = None,
        existing_dataset: tuple[object, ...] | None = None,
        distinct_values: dict[str, list[str]] | None = None,
        legacy_rows: list[tuple[object, ...]] | None = None,
        insert_id: int = 11,
    ):
        self.rows = rows or []
        self.delete_rowcount = delete_rowcount
        self.dashboard_rows = dashboard_rows or []
        self.existing_semesters = existing_semesters or []
        self.existing_dataset = existing_dataset
        self.distinct_values = distinct_values or {}
        self.legacy_rows = legacy_rows or []
        self.insert_id = insert_id
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> _Cursor:
        self.executed.append((query, params))
        if "SELECT id, snapshot_date" in query:
            return _Cursor(rows=self.legacy_rows)
        if "SELECT DISTINCT semester" in query:
            return _Cursor(rows=[(semester,) for semester in self.existing_semesters])
        if "WHERE report_date = %s" in query:
            return _Cursor(rows=[self.existing_dataset] if self.existing_dataset else [])
        for column in ("fachbereich", "studiengang", "status"):
            if f"SELECT DISTINCT {column}" in query:
                return _Cursor(rows=[(value,) for value in self.distinct_values.get(column, [])])
        if "COUNT(*) AS anzahl" in query:
            return _Cursor(rows=self.dashboard_rows)
        if "WHERE report_date IS NOT NULL" in query:
            return _Cursor(rows=self.rows)
        if "SELECT id, filename" in query:
            return _Cursor(rows=self.rows)
        if "INSERT INTO import_batches" in query:
            return _Cursor(rows=[(self.insert_id,)])
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


def test_semester_label_formatiert_fachliche_labels() -> None:
    assert semester_label("SS2026") == "Sommersemester 2026"
    assert semester_label("WS2026_27") == "Wintersemester 2026/27"


def test_semester_date_range_bildet_bewerbungszeitraeume_ab() -> None:
    assert semester_date_range("WS2026_27") == (date(2026, 1, 16), date(2026, 6, 30))
    assert semester_date_range("SS2026") == (date(2025, 7, 1), date(2026, 1, 15))


def test_semester_from_snapshot_date_ordnet_legacy_daten_zu() -> None:
    assert semester_from_snapshot_date(date(2026, 1, 15)) == "SS2026"
    assert semester_from_snapshot_date(date(2026, 1, 16)) == "WS2026_27"
    assert semester_from_snapshot_date(date(2026, 6, 30)) == "WS2026_27"
    assert semester_from_snapshot_date(date(2026, 7, 1)) == "SS2027"


def test_build_semester_options_bietet_aktuelle_und_ruecklaufende_semester() -> None:
    options = build_semester_options(today=date(2026, 7, 1))

    assert [option.label for option in options[:2]] == [
        "Wintersemester 2026/27",
        "Sommersemester 2026",
    ]
    assert "Wintersemester 2020/21" in [option.label for option in options]
    assert "Sommersemester 2020" in [option.label for option in options]


def test_build_report_date_options_liefert_letzte_zehn_stichtage() -> None:
    options = build_report_date_options(today=date(2026, 8, 17))

    assert [option.value for option in options] == [
        date(2026, 8, 15),
        date(2026, 7, 31),
        date(2026, 7, 15),
        date(2026, 6, 30),
        date(2026, 6, 15),
        date(2026, 5, 31),
        date(2026, 5, 15),
        date(2026, 4, 30),
        date(2026, 4, 15),
        date(2026, 3, 31),
    ]


def test_build_report_date_options_beruecksichtigt_schaltjahr() -> None:
    options = build_report_date_options(today=date(2024, 3, 1))

    assert [option.value for option in options[:3]] == [
        date(2024, 2, 29),
        date(2024, 2, 15),
        date(2024, 1, 31),
    ]


def test_list_import_batches_mappt_db_rows() -> None:
    created_at = datetime(2026, 6, 8, 10, 30, tzinfo=UTC)
    conn = cast(
        Any,
        _FakeConnection(rows=[(7, "Export_110526.csv", date(2026, 8, 15), created_at, "Nico", 42)]),
    )

    batches = list_import_batches(conn)

    assert len(batches) == 1
    assert batches[0].id == 7
    assert batches[0].filename == "Export_110526.csv"
    assert batches[0].report_date == date(2026, 8, 15)
    assert dataset_label(batches[0]) == "Datenbestand vom 15.08.2026"
    assert batches[0].created_at == created_at
    assert batches[0].imported_by == "Nico"
    assert batches[0].row_count == 42


def test_import_cleaned_dataframe_speichert_neuen_datenbestand() -> None:
    fake_conn = _FakeConnection(insert_id=42)
    conn = cast(Any, fake_conn)

    batch_id = import_cleaned_dataframe(
        conn,
        pd.DataFrame([_row()]),
        filename="Export_110526.csv",
        report_date=date(2026, 8, 15),
        imported_by="Nico",
    )

    assert batch_id == 42
    assert not any("DELETE FROM import_batches" in query for query, _ in fake_conn.executed)
    assert any(
        "INSERT INTO import_batches" in query
        and params[0] == "Export_110526.csv"
        and params[1] is None
        and params[2] is None
        and params[3] == date(2026, 8, 15)
        for query, params in fake_conn.executed
    )


def test_import_cleaned_dataframe_lehnt_vorhandenes_berichtsdatum_ohne_bestaetigung_ab() -> None:
    created_at = datetime(2026, 8, 15, 10, 30, tzinfo=UTC)
    existing = (7, "alt.xlsx", date(2026, 8, 15), created_at, "Nico", 42)
    conn = cast(Any, _FakeConnection(existing_dataset=existing))

    with pytest.raises(DatasetAlreadyExistsError):
        import_cleaned_dataframe(
            conn,
            pd.DataFrame([_row()]),
            filename="neu.xlsx",
            report_date=date(2026, 8, 15),
            imported_by="Nico",
        )


def test_import_cleaned_dataframe_ersetzt_vorhandenes_berichtsdatum_mit_bestaetigung() -> None:
    created_at = datetime(2026, 8, 15, 10, 30, tzinfo=UTC)
    existing = (7, "alt.xlsx", date(2026, 8, 15), created_at, "Nico", 42)
    fake_conn = _FakeConnection(existing_dataset=existing, insert_id=43)
    conn = cast(Any, fake_conn)

    batch_id = import_cleaned_dataframe(
        conn,
        pd.DataFrame([_row()]),
        filename="neu.xlsx",
        report_date=date(2026, 8, 15),
        imported_by="Nico",
        replace_existing=True,
    )

    assert batch_id == 43
    assert ("DELETE FROM import_batches WHERE id = %s", (7,)) in fake_conn.executed


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


def test_get_dashboard_filter_options_mappt_db_rows() -> None:
    conn = cast(
        Any,
        _FakeConnection(
            rows=[
                (
                    7,
                    "Export_150826.xlsx",
                    date(2026, 8, 15),
                    datetime(2026, 8, 15, tzinfo=UTC),
                    "Nico",
                    42,
                ),
                (
                    8,
                    "Export_310726.xlsx",
                    date(2026, 7, 31),
                    datetime(2026, 7, 31, tzinfo=UTC),
                    "Nico",
                    40,
                ),
            ],
            distinct_values={
                "fachbereich": ["Gesundheit", "Technik"],
                "studiengang": ["Informatik", "Maschinenbau"],
                "status": ["Absage", "Akzeptiert"],
            },
        ),
    )

    options = get_dashboard_filter_options(conn)

    assert [dataset.report_date for dataset in options.datasets] == [
        date(2026, 8, 15),
        date(2026, 7, 31),
    ]
    assert options.fachbereiche == ["Gesundheit", "Technik"]
    assert options.studiengaenge == ["Informatik", "Maschinenbau"]
    assert options.statuses == ["Absage", "Akzeptiert"]


def test_load_dashboard_rows_mappt_aggregierte_db_rows() -> None:
    fake_conn = _FakeConnection(
        dashboard_rows=[
            (7, date(2026, 8, 15), "Technik", "Informatik", "Akzeptiert", 5),
            (7, date(2026, 8, 15), "Wirtschaft", "Marketing", "Absage", 3),
        ]
    )
    conn = cast(Any, fake_conn)
    filters = DashboardFilters(
        batch_ids=(7,),
        fachbereiche=("Technik",),
        studiengaenge=("Informatik",),
        statuses=("Akzeptiert",),
    )

    rows = load_dashboard_rows(conn, filters)

    assert rows.to_dict("records") == [
        {
            "dataset_id": 7,
            "report_date": date(2026, 8, 15),
            "fachbereich": "Technik",
            "studiengang": "Informatik",
            "status": "Akzeptiert",
            "anzahl": 5,
        },
        {
            "dataset_id": 7,
            "report_date": date(2026, 8, 15),
            "fachbereich": "Wirtschaft",
            "studiengang": "Marketing",
            "status": "Absage",
            "anzahl": 3,
        },
    ]
    executed_dashboard_query = [
        query for query, _ in fake_conn.executed if "COUNT(*) AS anzahl" in query
    ]
    assert executed_dashboard_query
    assert "b.id IN (%s)" in executed_dashboard_query[0]
    assert "a.fachbereich IN (%s)" in executed_dashboard_query[0]
    assert fake_conn.executed[-1][1] == (
        7,
        "Technik",
        "Informatik",
        "Akzeptiert",
    )
