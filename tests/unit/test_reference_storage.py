from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from typing import Any, Literal, cast

import pandas as pd
import pytest
from psycopg import sql

from bewerberzahlen.reference_import import ReferenceCount
from bewerberzahlen.reference_storage import (
    REFERENCE_TABLES,
    ReferenceKey,
    import_reference_counts,
    load_final_year_rows,
    reference_key,
)


def _value(*, count: int = 200, metric: Literal["BEW", "IMM"] = "BEW") -> ReferenceCount:
    return ReferenceCount("WS2025_26", "Informatik", metric, count, "Quelle", "B2", "Technik")


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _Transaction(AbstractContextManager[None]):
    def __init__(self, conn: FakeReferenceConnection) -> None:
        self.conn = conn
        self.original = conn.values.copy()

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        if exc_type is not None:
            self.conn.values = self.original
            self.conn.rollbacks += 1
        else:
            self.conn.commits += 1
        return False


class FakeReferenceConnection:
    """Transactional in-memory connection: a late insert failure must roll back both metrics."""

    def __init__(
        self, values: list[ReferenceCount] | None = None, *, fail_imm: bool = False
    ) -> None:
        self.values = {reference_key(value): value for value in values or []}
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fail_imm = fail_imm
        self.commits = 0
        self.rollbacks = 0

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def execute(self, query: sql.Composable, params: tuple[object, ...] = ()) -> _Cursor:
        statement = query.as_string()
        self.executed.append((statement, params))
        for metric, table in REFERENCE_TABLES.items():
            if table not in statement:
                continue
            if statement.startswith("SELECT"):
                semesters = cast(list[str], params[0]) if params else []
                return _Cursor(
                    [
                        (
                            v.semester,
                            v.fachbereich,
                            v.studiengang,
                            v.count,
                            v.sheet_name,
                            v.source_cell,
                        )
                        for v in self.values.values()
                        if v.metric == metric and (not semesters or v.semester in semesters)
                    ]
                )
            if "INSERT INTO" in statement:
                if self.fail_imm and metric == "IMM":
                    raise RuntimeError("Simulierter Schreibfehler")
                value = ReferenceCount(
                    str(params[0]),
                    str(params[2]),
                    metric,
                    int(cast(int, params[3])),
                    str(params[5]),
                    str(params[6]),
                    str(params[1]),
                )
                self.values[reference_key(value)] = value
                break
        return _Cursor([])


def test_independent_imports_keep_other_metrics_semesters_and_omitted_keys() -> None:
    bew = _value()
    historical = replace(bew, semester="WS2024_25", count=50)
    fake = FakeReferenceConnection([bew, historical])
    imm = _value(count=150, metric="IMM")
    assert (
        import_reference_counts(cast(Any, fake), [imm], filename="neu.xlsx", imported_by=" Test ")
        == 1
    )
    assert fake.values == {reference_key(value): value for value in [bew, historical, imm]}
    assert fake.commits == 1
    insert = next(params for query, params in fake.executed if "INSERT INTO" in query)
    assert insert[-1] == "Test"
    assert not any(
        "applications" in query or "import_batches" in query for query, _ in fake.executed
    )


def test_existing_values_require_confirmation_and_preview_must_still_match() -> None:
    old = _value(count=100)
    new = _value()
    fake = FakeReferenceConnection([old])
    conn = cast(Any, fake)
    with pytest.raises(ValueError, match="Ersetzen"):
        import_reference_counts(conn, [new], filename="neu.xlsx", imported_by="Test")
    with pytest.raises(ValueError, match="inzwischen geändert"):
        import_reference_counts(
            conn,
            [new],
            filename="neu.xlsx",
            imported_by="Test",
            replace_existing=True,
            expected_existing={reference_key(old): 90},
        )
    assert fake.values[reference_key(old)].count == 100
    import_reference_counts(
        conn,
        [new],
        filename="neu.xlsx",
        imported_by="Test",
        replace_existing=True,
        expected_existing={reference_key(old): 100},
    )
    assert fake.values[reference_key(new)].count == 200
    assert fake.rollbacks == 2


def test_late_failure_rolls_back_bew_and_imm_together() -> None:
    fake = FakeReferenceConnection(fail_imm=True)
    with pytest.raises(RuntimeError, match="Schreibfehler"):
        import_reference_counts(
            cast(Any, fake),
            [_value(), _value(metric="IMM", count=150)],
            filename="neu.xlsx",
            imported_by="Test",
        )
    assert not fake.values
    assert fake.rollbacks == 1
    assert fake.commits == 0


def test_report_inputs_keep_missing_as_null_and_zero_as_zero_and_filter_semester() -> None:
    fake = FakeReferenceConnection(
        [
            _value(count=0),
            replace(_value(metric="IMM", count=150), studiengang="Maschinenbau"),
            replace(_value(count=999), semester="WS2024_25"),
        ]
    )
    rows = load_final_year_rows(cast(Any, fake), "WS2025_26")
    assert rows.loc[0, "BEW VJ final"] == 0
    assert pd.isna(rows.loc[0, "IMM VJ final"])
    assert pd.isna(rows.loc[1, "BEW VJ final"])
    assert rows.loc[1, "IMM VJ final"] == 150
    assert str(rows["BEW VJ final"].dtype) == "Int64"
    assert len(rows) == 2


def test_empty_storage_has_typed_report_columns_and_schema_is_additive() -> None:
    fake = FakeReferenceConnection()
    assert load_final_year_rows(cast(Any, fake), "WS2025_26").empty
    assert all(
        "CREATE TABLE IF NOT EXISTS" in query and "PRIMARY KEY" in query
        for query, _ in fake.executed
        if "CREATE TABLE" in query
    )


def test_invalid_inputs_are_rejected_before_any_database_write() -> None:
    fake = FakeReferenceConnection()
    with pytest.raises(ValueError, match="Anzahl"):
        import_reference_counts(
            cast(Any, fake), [_value(count=-1)], filename="neu.xlsx", imported_by="Test"
        )
    assert not fake.executed


def test_new_value_after_preview_requires_a_fresh_preview() -> None:
    fake = FakeReferenceConnection([_value()])
    with pytest.raises(ValueError, match="inzwischen geändert"):
        import_reference_counts(
            cast(Any, fake),
            [_value(count=300)],
            filename="neu.xlsx",
            imported_by="Test",
            expected_existing=cast(dict[ReferenceKey, int], {}),
        )
