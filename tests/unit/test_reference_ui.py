from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from bewerberzahlen.reference_import import ReferenceCount
from bewerberzahlen.reference_storage import ReferenceKey
from bewerberzahlen.reports import REPORT_DEFINITIONS
from bewerberzahlen.storage import DashboardFilterOptions, DashboardFilters, ExistingImport

PREVIEW_APP = """
from app_pages.reference_import_page import render_reference_preview
from bewerberzahlen.mapping import ProgramEntry, ProgramResolver
from bewerberzahlen.reference_import import ReferenceCount
resolver = ProgramResolver.from_programs([
    ProgramEntry("Informatik", "Technik", []),
    ProgramEntry("Maschinenbau", "Technik", []),
])
values = [
    ReferenceCount("WS2025_26", "Informatik", "BEW", 200, "Quelle", "B2"),
    ReferenceCount("WS2025_26", "Informatik", "IMM", 150, "Quelle", "C2"),
]
render_reference_preview(values, "zahlen.xlsx", resolver)
"""


def _preview(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stored: list[ReferenceCount] | None = None,
) -> tuple[AppTest, list[dict[str, object]]]:
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app_pages.reference_import_page.get_database_url", lambda: "postgresql://test"
    )
    monkeypatch.setattr(
        "app_pages.reference_import_page.connection_from_url", lambda _url: nullcontext()
    )
    monkeypatch.setattr(
        "app_pages.reference_import_page.load_reference_counts",
        lambda _conn, *, semesters: stored or [],
    )

    def save(
        _conn: object,
        values: list[ReferenceCount],
        *,
        filename: str,
        imported_by: str,
        replace_existing: bool,
        expected_existing: dict[ReferenceKey, int],
    ) -> int:
        saved.append(
            {
                "values": values,
                "filename": filename,
                "imported_by": imported_by,
                "replace_existing": replace_existing,
                "expected_existing": expected_existing,
            }
        )
        return len(values)

    monkeypatch.setattr("app_pages.reference_import_page.import_reference_counts", save)
    return AppTest.from_string(PREVIEW_APP).run(), saved


def test_preview_does_not_save_without_confirmation_and_passes_checked_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, saved = _preview(monkeypatch)
    assert not app.exception
    assert len(app.dataframe) == 1
    app.text_input(key="reference_imported_by").set_value("Test")
    app.button[0].click().run()
    assert not saved
    assert "ausdrücklich bestätigen" in app.error[0].value
    app.checkbox[0].check()
    app.button[0].click().run()
    assert not app.exception
    assert len(saved) == 1
    assert saved[0]["replace_existing"] is False
    assert saved[0]["expected_existing"] == {}
    assert saved[0]["filename"] == "zahlen.xlsx"
    assert saved[0]["values"] == [
        ReferenceCount("WS2025_26", "Informatik", "BEW", 200, "Quelle", "B2", "Technik"),
        ReferenceCount("WS2025_26", "Informatik", "IMM", 150, "Quelle", "C2", "Technik"),
    ]
    assert app.success[0].value == "2 Semesterreferenzen wurden gespeichert."


def test_existing_values_are_shown_and_need_separate_replacement_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = ReferenceCount("WS2025_26", "Informatik", "BEW", 100, "Alt", "B2", "Technik")
    app, saved = _preview(monkeypatch, stored=[existing])
    assert app.dataframe[0].value.loc[0, "Bisher"] == 100
    app.text_input(key="reference_imported_by").set_value("Test")
    app.checkbox[0].check()
    app.button[0].click().run()
    assert not saved
    app.checkbox[1].check()
    app.button[0].click().run()
    assert not app.exception
    assert saved[0]["replace_existing"] is True
    assert saved[0]["expected_existing"] == {("BEW", "WS2025_26", "Technik", "Informatik"): 100}


def test_changed_assignment_invalidates_previous_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, saved = _preview(monkeypatch)
    app.checkbox[0].check().run()
    app.selectbox(key="reference_program_Informatik").select("Maschinenbau").run()
    assert not app.checkbox[0].value
    app.button[0].click().run()
    assert not saved


def test_preview_is_available_without_database_but_save_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preview(monkeypatch)
    monkeypatch.setattr("app_pages.reference_import_page.get_database_url", lambda: None)
    app = AppTest.from_string(PREVIEW_APP).run()
    assert not app.exception
    assert len(app.dataframe) == 1
    assert not app.button
    assert "Speichern ist deaktiviert" in app.info[0].value


def test_unknown_program_assignment_and_post_assignment_duplicates_block_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _preview(monkeypatch)
    script = PREVIEW_APP.replace('"Informatik", "BEW", 200', '"Alt", "BEW", 200')
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert not app.dataframe
    assert not app.button
    app.selectbox(key="reference_program_Alt").select("Informatik").run()
    assert len(app.dataframe) == 1
    # A second BEW row assigned to the same target is a collision, not an implicit sum.
    script = script.replace('"Informatik", "IMM", 150', '"Informatik", "BEW", 150')
    app = AppTest.from_string(script).run()
    app.selectbox(key="reference_program_Alt").select("Informatik").run()
    assert not app.dataframe
    assert "Doppelte Referenz" in app.info[0].value


def test_altbestaende_offers_separate_reference_import_without_database_access() -> None:
    path = Path(__file__).resolve().parents[2] / "src/app_pages/historical_import_page.py"
    app = AppTest.from_file(str(path)).run()
    app.selectbox(key="historical_import_kind").select("Semesterreferenzen (BEW / IMM)").run()
    assert not app.exception
    assert app.multiselect(key="reference_metrics").value == ["BEW", "IMM"]
    assert len(app.get("file_uploader")) == 1


def test_dashboard_uses_same_date_prior_year_and_explicit_winter_reference_with_partial_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = ExistingImport(
        1, "aktuell.xlsx", date(2026, 7, 15), datetime(2026, 7, 15), "Test", 120
    )
    previous = ExistingImport(
        2, "vorjahr.xlsx", date(2025, 7, 15), datetime(2025, 7, 15), "Test", 80
    )
    options = DashboardFilterOptions([dataset], ["Technik"], ["Informatik"], ["Offen"])
    dates: list[date] = []
    semesters: list[str] = []

    def find_dataset(_conn: object, report_date: date) -> ExistingImport:
        dates.append(report_date)
        return previous

    def load_rows(_conn: object, filters: DashboardFilters) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "fachbereich": "Technik",
                    "studiengang": "Informatik",
                    "status": "Offen",
                    "anzahl": 120 if filters.batch_ids == (1,) else 80,
                    "dataset_id": filters.batch_ids[0],
                    "report_date": dataset.report_date,
                }
            ]
        )

    def load_final(_conn: object, semester: str) -> pd.DataFrame:
        semesters.append(semester)
        if semester != "WS2025_26":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "fachbereich": "Technik",
                    "studiengang": "Informatik",
                    "BEW VJ final": 200,
                    "IMM VJ final": 150,
                }
            ]
        )

    monkeypatch.setattr("bewerberzahlen.app_config.get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr("bewerberzahlen.storage.connection_from_url", lambda _url: nullcontext())
    monkeypatch.setattr(
        "bewerberzahlen.storage.get_dashboard_filter_options", lambda _conn: options
    )
    monkeypatch.setattr("bewerberzahlen.storage.find_dataset_by_report_date", find_dataset)
    monkeypatch.setattr("bewerberzahlen.storage.load_dashboard_rows", load_rows)
    monkeypatch.setattr("bewerberzahlen.reference_storage.load_final_year_rows", load_final)
    path = Path(__file__).resolve().parents[2] / "src/app_pages/dashboard_page.py"
    app = AppTest.from_file(str(path)).run()
    app.selectbox(key="dashboard_report").select(REPORT_DEFINITIONS[1]).run()
    assert not app.exception
    assert not app.error
    assert dates[-1] == date(2025, 7, 15)
    assert semesters[-1] == "WS2025_26"
    html = app.get("html")[0].proto.body
    assert "40,0 %" in html and "75,0 %" in html
    assert ">300</td>" in html and ">225</td>" in html
    assert not app.warning
    app.number_input(key="wise_target_year_1").set_value(2027).run()
    assert not app.exception
    assert semesters[-1] == "WS2026_27"
    assert "Teilbasis" in app.warning[0].value
    assert "Informatik: Finale BEW und IMM fehlen" in app.warning[0].value
