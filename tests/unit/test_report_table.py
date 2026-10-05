from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from streamlit.testing.v1 import AppTest

from bewerberzahlen.report_table import render_bewerbungszahlen_wise_table
from bewerberzahlen.reports import (
    ACCEPTED_DELTA_COLUMN,
    ACCEPTED_DELTA_PERCENT_COLUMN,
    APPLICATIONS_DELTA_COLUMN,
    APPLICATIONS_DELTA_PERCENT_COLUMN,
    PLACEHOLDER_COLUMNS,
    PROGRAM_COLUMN,
    REPORT_COLUMNS,
    REPORT_DEFINITIONS,
    ROW_TYPE_COLUMN,
    build_bewerbungszahlen_wise_report,
)
from bewerberzahlen.storage import DashboardFilterOptions, DashboardFilters, ExistingImport


def _report() -> pd.DataFrame:
    current = pd.DataFrame(
        [
            {
                "fachbereich": "Technik",
                "studiengang": "Informatik",
                "status": "Akzeptiert",
                "anzahl": 6,
            },
            {"fachbereich": "Wirtschaft", "studiengang": "Finance", "status": "Offen", "anzahl": 2},
        ]
    )
    previous = current.copy()
    previous["anzahl"] = [4, 8]
    return build_bewerbungszahlen_wise_report(current, previous)


def _parse(report: pd.DataFrame, *, dark_mode: bool = False) -> ET.Element:
    return ET.fromstring(
        f"<root>{render_bewerbungszahlen_wise_table(report, dark_mode=dark_mode)}</root>"
    )


def test_table_group_headers_cover_all_visible_columns_in_report_order() -> None:
    root = _parse(_report())
    heading_rows = root.findall("./div/table/thead/tr")
    assert len(heading_rows) == 2
    program_heading, *groups = list(heading_rows[0])
    assert program_heading.text == PROGRAM_COLUMN
    assert program_heading.get("rowspan") == "2"
    assert [(group.text, group.get("colspan")) for group in groups] == [
        ("Zahlen laufende Bewerberphase", "5"),
        ("Vergleich akzeptierter Bewerbungen", "3"),
        ("Vergleich aller Bewerbungen", "3"),
        ("Prognosen auf Basis der Vorjahreswerte", "6"),
        ("Aktueller Zielwert", "4"),
    ]
    assert all(group.get("scope") == "colgroup" for group in groups)
    assert [cell.text for cell in heading_rows[1]] == REPORT_COLUMNS[1:-1]
    assert len(root.findall("./div/table/colgroup/col")) == len(REPORT_COLUMNS) - 1
    for row in root.findall("./div/table/tbody/tr"):
        assert len(row) == len(REPORT_COLUMNS) - 1


def test_table_aligns_group_boundaries_in_headers_and_every_body_row() -> None:
    root = _parse(_report())
    expected = [0, 5, 8, 11, 17]
    headings = root.findall("./div/table/thead/tr")[1]
    assert [i for i, cell in enumerate(headings) if cell.get("class") == "group-start"] == expected
    for row in root.findall("./div/table/tbody/tr"):
        assert [
            i
            for i, cell in enumerate(row.findall("td"))
            if "group-start" in cell.get("class", "").split()
        ] == expected


def test_table_preserves_data_and_row_order_and_styles_selection_total_by_row_type() -> None:
    report = _report()
    report[PROGRAM_COLUMN] = report[PROGRAM_COLUMN].replace({"Gesamtsumme": "Summe Auswahl"})
    original = report.copy(deep=True)
    rows = _parse(report).findall("./div/table/tbody/tr")

    assert [row.findtext("th") for row in rows] == [
        "Informatik",
        "Fachbereich Technik",
        "Finance",
        "Fachbereich Wirtschaft",
        "Summe Auswahl",
    ]
    assert [row.get("class") for row in rows] == ["", "subtotal", "", "subtotal", "total"]
    assert [row.findtext("td") for row in rows] == ["6", "6", "2", "2", "8"]
    assert_frame_equal(report, original)


@pytest.mark.parametrize(
    ("column", "positive", "negative", "zero"),
    [
        (ACCEPTED_DELTA_COLUMN, "+2", "-2", "0"),
        (APPLICATIONS_DELTA_COLUMN, "+2", "-2", "0"),
        (ACCEPTED_DELTA_PERCENT_COLUMN, "+2,0 %", "-2,0 %", "0,0 %"),
        (APPLICATIONS_DELTA_PERCENT_COLUMN, "+2,0 %", "-2,0 %", "0,0 %"),
    ],
)
def test_table_formats_and_colors_signed_deltas(
    column: str, positive: str, negative: str, zero: str
) -> None:
    report = _report()
    report[column] = [2, 2, -2, -2, 0]
    cells = [
        row.findall("td")[REPORT_COLUMNS.index(column) - 1]
        for row in _parse(report).findall("./div/table/tbody/tr")
    ]
    assert [cell.text for cell in cells] == [positive, positive, negative, negative, zero]
    assert all("positive" in cell.get("class", "") for cell in cells[:2])
    assert all("negative" in cell.get("class", "") for cell in cells[2:4])
    assert "positive" not in cells[4].get("class", "")
    assert "negative" not in cells[4].get("class", "")


def test_table_retains_missing_previous_year_and_forecast_placeholders() -> None:
    report = _report()
    for column in PLACEHOLDER_COLUMNS:
        report[column] = "-"
    for row in _parse(report).findall("./div/table/tbody/tr"):
        assert [cell.text for cell in row.findall("td")[5:]] == ["-"] * len(PLACEHOLDER_COLUMNS)


def test_table_escapes_text_and_cannot_inject_html_or_css_classes() -> None:
    report = _report()
    malicious = '<script>alert("test")</script> & <img src="x" onerror="alert(1)">'
    report.loc[0, PROGRAM_COLUMN] = malicious
    report.loc[0, "Prognose BEW"] = malicious
    report.loc[0, ROW_TYPE_COLUMN] = '"><script>alert(1)</script>'
    root = _parse(report)
    row = root.findall("./div/table/tbody/tr")[0]

    assert row.findtext("th") == malicious
    assert row.findall("td")[11].text == malicious
    assert row.get("class") == ""
    assert root.findall(".//script") == []
    assert root.findall(".//img") == []


@pytest.mark.parametrize("dark_mode", [False, True])
def test_table_provides_keyboard_access_and_explicit_theme(dark_mode: bool) -> None:
    root = _parse(_report(), dark_mode=dark_mode)
    wrapper = root.find("div")
    assert wrapper is not None
    assert wrapper.get("class") == ("wise-report dark" if dark_mode else "wise-report")
    assert wrapper.get("tabindex") == "0"
    assert wrapper.get("role") == "region"
    assert wrapper.get("aria-label")
    assert all(cell.get("scope") == "row" for cell in root.findall("./div/table/tbody/tr/th"))


def test_table_handles_empty_report_with_valid_headers() -> None:
    report = build_bewerbungszahlen_wise_report(pd.DataFrame())
    root = _parse(report)
    assert len(root.findall("./div/table/thead/tr")) == 2
    assert root.findall("./div/table/tbody/tr") == []


def test_table_formats_forecast_ratios_and_rounds_only_display_values() -> None:
    report = _report()
    report["Zielerreichung per dato/final"] = 0.4
    report["Wandlung IMM/BEW"] = 0.7555
    report["Prognose BEW"] = 12.6
    original = report.copy(deep=True)
    cells = _parse(report).findall("./div/table/tbody/tr")[0].findall("td")
    assert cells[REPORT_COLUMNS.index("Prognose BEW") - 1].text == "13"
    assert cells[REPORT_COLUMNS.index("Zielerreichung per dato/final") - 1].text == "40,0 %"
    assert cells[REPORT_COLUMNS.index("Wandlung IMM/BEW") - 1].text == "75,5 %"
    assert_frame_equal(report, original)


def test_table_rejects_missing_report_columns_with_clear_error() -> None:
    report = _report().drop(columns=[PROGRAM_COLUMN, "Zielwert"])
    with pytest.raises(ValueError, match="Studiengang / Bereich, Zielwert"):
        render_bewerbungszahlen_wise_table(report)


def test_dashboard_renders_grouped_report_and_preserves_filtered_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = ExistingImport(1, "current.xlsx", date(2026, 3, 15), datetime(2026, 3, 15), "Test", 6)
    previous_dataset = ExistingImport(
        2, "previous.xlsx", date(2025, 3, 15), datetime(2025, 3, 15), "Test", 4
    )
    options = DashboardFilterOptions([dataset], ["Technik"], ["Informatik"], ["Akzeptiert"])

    def load_rows(_connection: object, filters: DashboardFilters) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "fachbereich": "Technik",
                    "studiengang": "Informatik",
                    "status": "Akzeptiert",
                    "anzahl": 6 if filters.batch_ids == (1,) else 4,
                    "dataset_id": filters.batch_ids[0],
                    "report_date": dataset.report_date,
                }
            ]
        )

    monkeypatch.setattr("bewerberzahlen.app_config.get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr("bewerberzahlen.storage.connection_from_url", lambda _url: nullcontext())
    monkeypatch.setattr(
        "bewerberzahlen.storage.get_dashboard_filter_options", lambda _conn: options
    )
    monkeypatch.setattr(
        "bewerberzahlen.storage.find_dataset_by_report_date", lambda _conn, _date: previous_dataset
    )
    monkeypatch.setattr("bewerberzahlen.storage.load_dashboard_rows", load_rows)
    monkeypatch.setattr(
        "bewerberzahlen.reference_storage.load_final_year_rows",
        lambda _conn, _semester: pd.DataFrame(),
    )
    page_path = Path(__file__).resolve().parents[2] / "src/app_pages/dashboard_page.py"
    app = AppTest.from_file(str(page_path), default_timeout=15).run()
    assert not app.exception
    app.selectbox(key="dashboard_report").select(REPORT_DEFINITIONS[1]).run()
    assert not app.exception
    assert not app.error
    assert len(app.get("html")) == 1
    report_html = app.get("html")[0].proto.body
    assert "Zahlen laufende Bewerberphase" in report_html
    assert '<tr class="total">' in report_html

    app.multiselect(key="bewerbungszahlen_wise_fachbereiche").select("Technik").run()
    assert not app.exception
    assert not app.error
    report_html = app.get("html")[0].proto.body
    root = ET.fromstring(f"<root>{report_html}</root>")
    total = root.findall("./div/table/tbody/tr")[-1]
    assert total.get("class") == "total"
    assert total.findtext("th") == "Summe Auswahl"
    assert total.findtext("td") == "6"
    assert app.get("html")[0].proto.unsafe_allow_javascript is False
