from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from bewerberzahlen.mapping import ProgramEntry, ProgramResolver
from bewerberzahlen.reports import (
    COMPLETION_COLUMN,
    CONVERSION_COLUMN,
    FINAL_APPLICATIONS_COLUMN,
    FINAL_ENROLLMENTS_COLUMN,
    FORECAST_APPLICATIONS_COLUMN,
    FORECAST_ENROLLMENTS_COLUMN,
    PROGRAM_COLUMN,
    REPORT_COLUMNS,
    build_bewerbungszahlen_wise_report,
    forecast_reference_warnings,
)


def _snapshot(count: int, program: str = "Informatik") -> pd.DataFrame:
    return pd.DataFrame(
        [{"fachbereich": "Technik", "studiengang": program, "status": "Offen", "anzahl": count}]
    )


def _final(
    bew: int | None = 200, imm: int | None = 150, program: str = "Informatik"
) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "fachbereich": "Technik",
                "studiengang": program,
                FINAL_APPLICATIONS_COLUMN: bew,
                FINAL_ENROLLMENTS_COLUMN: imm,
            }
        ]
    )
    for column in (FINAL_APPLICATIONS_COLUMN, FINAL_ENROLLMENTS_COLUMN):
        frame[column] = pd.array(frame[column].tolist(), dtype="Int64")
    return frame


def test_all_six_metrics_follow_the_agreed_example_and_do_not_mutate_inputs() -> None:
    current, previous, final = _snapshot(120), _snapshot(80), _final()
    originals = [frame.copy(deep=True) for frame in (current, previous, final)]
    report = build_bewerbungszahlen_wise_report(current, previous, previous_year_final_rows=final)
    for column, expected in (
        (FINAL_APPLICATIONS_COLUMN, 200),
        (FINAL_ENROLLMENTS_COLUMN, 150),
        (COMPLETION_COLUMN, 0.4),
        (CONVERSION_COLUMN, 0.75),
        (FORECAST_APPLICATIONS_COLUMN, 300),
        (FORECAST_ENROLLMENTS_COLUMN, 225),
    ):
        assert report[column].eq(expected).all()
    assert report.columns.tolist() == REPORT_COLUMNS
    assert forecast_reference_warnings(report) == []
    for actual, original in zip((current, previous, final), originals, strict=True):
        assert_frame_equal(actual, original)


@pytest.mark.parametrize(
    ("previous", "bew", "imm", "completion", "conversion", "forecast", "forecast_imm"),
    [
        (80, 0, 0, "-", "-", "-", "-"),
        (0, 200, 150, 0.0, 0.75, "-", "-"),
        (80, None, 150, "-", "-", "-", "-"),
        (80, 200, None, 0.4, "-", 300.0, "-"),
        (80, 200, 0, 0.4, 0.0, 300.0, 0.0),
    ],
)
def test_missing_and_zero_counts_have_independent_metric_dependencies(
    previous: int,
    bew: int | None,
    imm: int | None,
    completion: float | str,
    conversion: float | str,
    forecast: float | str,
    forecast_imm: float | str,
) -> None:
    report = build_bewerbungszahlen_wise_report(
        _snapshot(120), _snapshot(previous), previous_year_final_rows=_final(bew, imm)
    )
    for column, expected in (
        (COMPLETION_COLUMN, completion),
        (CONVERSION_COLUMN, conversion),
        (FORECAST_APPLICATIONS_COLUMN, forecast),
        (FORECAST_ENROLLMENTS_COLUMN, forecast_imm),
    ):
        assert report[column].eq(expected).all()
    assert report[FINAL_APPLICATIONS_COLUMN].eq(bew if bew is not None else "-").all()
    assert report[FINAL_ENROLLMENTS_COLUMN].eq(imm if imm is not None else "-").all()


def test_missing_previous_snapshot_retains_final_counts_and_conversion() -> None:
    report = build_bewerbungszahlen_wise_report(_snapshot(120), previous_year_final_rows=_final())
    assert report[CONVERSION_COLUMN].eq(0.75).all()
    assert report[FINAL_APPLICATIONS_COLUMN].eq(200).all()
    assert report[COMPLETION_COLUMN].eq("-").all()
    assert report[FORECAST_APPLICATIONS_COLUMN].eq("-").all()
    assert report[FORECAST_ENROLLMENTS_COLUMN].eq("-").all()


def test_zero_current_count_produces_zero_forecasts_with_valid_baseline() -> None:
    report = build_bewerbungszahlen_wise_report(
        _snapshot(0), _snapshot(80), previous_year_final_rows=_final()
    )
    assert report[FORECAST_APPLICATIONS_COLUMN].eq(0).all()
    assert report[FORECAST_ENROLLMENTS_COLUMN].eq(0).all()


def test_summaries_recompute_ratios_and_forecasts_from_sums_not_individual_forecasts() -> None:
    current = pd.concat([_snapshot(120), _snapshot(30, "Maschinenbau")])
    previous = pd.concat([_snapshot(80), _snapshot(50, "Maschinenbau")])
    final = pd.concat(
        [_final(), _final(100, 20, "Maschinenbau"), _final(999, 999, "Nicht ausgewählt")]
    )
    report = build_bewerbungszahlen_wise_report(current, previous, previous_year_final_rows=final)
    for label in ("Fachbereich Technik", "Gesamtsumme"):
        row = report[report[PROGRAM_COLUMN] == label].iloc[0]
        assert row[FINAL_APPLICATIONS_COLUMN] == 300
        assert row[FINAL_ENROLLMENTS_COLUMN] == 170
        assert row[COMPLETION_COLUMN] == pytest.approx(130 / 300)
        assert row[CONVERSION_COLUMN] == pytest.approx(170 / 300)
        assert row[FORECAST_APPLICATIONS_COLUMN] == pytest.approx(150 * 300 / 130)
        assert row[FORECAST_ENROLLMENTS_COLUMN] == pytest.approx(150 * 170 / 130)


def test_partial_basis_includes_all_current_and_prior_counts_and_reports_missing_references() -> (
    None
):
    current = pd.concat([_snapshot(120), _snapshot(30, "Neu")])
    previous = pd.concat([_snapshot(80), _snapshot(20, "Neu")])
    report = build_bewerbungszahlen_wise_report(
        current, previous, previous_year_final_rows=_final()
    )
    total = report.iloc[-1]
    assert total[FINAL_APPLICATIONS_COLUMN] == 200
    assert total[COMPLETION_COLUMN] == 0.5
    assert total[FORECAST_APPLICATIONS_COLUMN] == 300
    assert total[FORECAST_ENROLLMENTS_COLUMN] == 225
    assert "Neu: Finale BEW und IMM fehlen." in forecast_reference_warnings(report)
    new = report[report[PROGRAM_COLUMN] == "Neu"].iloc[0]
    assert new[FORECAST_APPLICATIONS_COLUMN] == "-"


def test_completely_missing_final_sums_stay_missing_instead_of_becoming_zero() -> None:
    for final in (pd.DataFrame(), _final(None, None)):
        report = build_bewerbungszahlen_wise_report(
            _snapshot(120), _snapshot(80), previous_year_final_rows=final
        )
        assert report[FINAL_APPLICATIONS_COLUMN].eq("-").all()
        assert report[FINAL_ENROLLMENTS_COLUMN].eq("-").all()
        assert report[FORECAST_APPLICATIONS_COLUMN].eq("-").all()


def test_ratios_above_one_are_not_clamped_and_are_reported() -> None:
    report = build_bewerbungszahlen_wise_report(
        _snapshot(120), _snapshot(250), previous_year_final_rows=_final(200, 220)
    )
    assert report[COMPLETION_COLUMN].eq(1.25).all()
    assert report[CONVERSION_COLUMN].eq(1.1).all()
    warnings = forecast_reference_warnings(report)
    assert any("IMM übersteigen" in warning for warning in warnings)
    assert any("Vorjahresstichtag übersteigen" in warning for warning in warnings)


def test_final_reference_aliases_match_without_renaming_report_labels() -> None:
    resolver = ProgramResolver.from_programs([ProgramEntry("Informatik", "Technik", ["Alt"])])
    report = build_bewerbungszahlen_wise_report(
        _snapshot(120, "Alt"),
        _snapshot(80, "Alt"),
        previous_year_final_rows=_final(),
        program_resolver=resolver,
    )
    assert report.iloc[0][PROGRAM_COLUMN] == "Alt"
    assert report.iloc[0][FORECAST_APPLICATIONS_COLUMN] == 300
    with pytest.raises(ValueError, match="Mehrdeutige"):
        build_bewerbungszahlen_wise_report(
            pd.concat([_snapshot(120), _snapshot(1, "Alt")]),
            previous_year_final_rows=_final(),
            program_resolver=resolver,
        )


@pytest.mark.parametrize("value", [-1, 1.5, float("inf"), float("nan"), True, "200"])
def test_invalid_final_counts_are_rejected_except_missing_nan(value: object) -> None:
    final = _final()
    final[FINAL_APPLICATIONS_COLUMN] = pd.Series([value], dtype=object)
    if isinstance(value, float) and pd.isna(value):
        report = build_bewerbungszahlen_wise_report(_snapshot(120), previous_year_final_rows=final)
        assert report[FINAL_APPLICATIONS_COLUMN].eq("-").all()
    else:
        with pytest.raises(ValueError, match="Ungültige finale Semesterzahl"):
            build_bewerbungszahlen_wise_report(_snapshot(120), previous_year_final_rows=final)


def test_duplicate_reference_rows_and_missing_columns_are_rejected() -> None:
    with pytest.raises(ValueError, match="Mehrdeutige"):
        build_bewerbungszahlen_wise_report(
            _snapshot(120), previous_year_final_rows=pd.concat([_final(), _final()])
        )
    with pytest.raises(ValueError, match="Referenzspalten fehlen"):
        build_bewerbungszahlen_wise_report(
            _snapshot(120),
            previous_year_final_rows=_final().drop(columns=[FINAL_ENROLLMENTS_COLUMN]),
        )
