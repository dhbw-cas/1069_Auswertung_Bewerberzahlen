from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from numbers import Real
from typing import cast

import pandas as pd

from .mapping import ProgramResolver


@dataclass(frozen=True)
class ReportDefinition:
    id: str
    label: str


OVERVIEW_REPORT_ID = "overview"
BEWERBUNGSZAHLEN_WISE_REPORT_ID = "bewerbungszahlen_wise"

REPORT_DEFINITIONS = (
    ReportDefinition(id=OVERVIEW_REPORT_ID, label="Übersicht"),
    ReportDefinition(id=BEWERBUNGSZAHLEN_WISE_REPORT_ID, label="Bewerbungszahlen WiSe"),
)

PROGRAM_COLUMN = "Studiengang / Bereich"
ROW_TYPE_COLUMN = "Zeilentyp"
PER_DATO_COLUMN = "per dato"
ACCEPTED_COLUMN = "davon akzeptiert"
OPEN_COLUMN = "davon offen"
NO_POTENTIAL_COLUMN = "kein Potential"
REJECTIONS_COLUMN = "Absagen"
ACCEPTED_PREVIOUS_YEAR_COLUMN = "Akzeptiert VJ per dato"
ACCEPTED_DELTA_COLUMN = "Akzeptiert Δ"
ACCEPTED_DELTA_PERCENT_COLUMN = "Akzeptiert Δ %"
APPLICATIONS_PREVIOUS_YEAR_COLUMN = "Alle Bewerbungen VJ per dato"
APPLICATIONS_DELTA_COLUMN = "Alle Bewerbungen Δ"
APPLICATIONS_DELTA_PERCENT_COLUMN = "Alle Bewerbungen Δ %"
FORECAST_APPLICATIONS_COLUMN = "Prognose BEW"
FORECAST_ENROLLMENTS_COLUMN = "Prognose IMM"
FINAL_APPLICATIONS_COLUMN = "BEW VJ final"
COMPLETION_COLUMN = "Zielerreichung per dato/final"
FINAL_ENROLLMENTS_COLUMN = "IMM VJ final"
CONVERSION_COLUMN = "Wandlung IMM/BEW"

PREVIOUS_YEAR_COMPARISONS = (
    (
        ACCEPTED_COLUMN,
        ACCEPTED_PREVIOUS_YEAR_COLUMN,
        ACCEPTED_DELTA_COLUMN,
        ACCEPTED_DELTA_PERCENT_COLUMN,
    ),
    (
        PER_DATO_COLUMN,
        APPLICATIONS_PREVIOUS_YEAR_COLUMN,
        APPLICATIONS_DELTA_COLUMN,
        APPLICATIONS_DELTA_PERCENT_COLUMN,
    ),
)

PLACEHOLDER_COLUMNS = [
    ACCEPTED_PREVIOUS_YEAR_COLUMN,
    ACCEPTED_DELTA_COLUMN,
    ACCEPTED_DELTA_PERCENT_COLUMN,
    APPLICATIONS_PREVIOUS_YEAR_COLUMN,
    APPLICATIONS_DELTA_COLUMN,
    APPLICATIONS_DELTA_PERCENT_COLUMN,
    FORECAST_APPLICATIONS_COLUMN,
    FORECAST_ENROLLMENTS_COLUMN,
    FINAL_APPLICATIONS_COLUMN,
    COMPLETION_COLUMN,
    FINAL_ENROLLMENTS_COLUMN,
    CONVERSION_COLUMN,
    "IMM VJ",
    "Zielwert",
    "Vergleich Zielwert",
    "Zielerreichung per dato",
]

REPORT_COLUMNS = [
    PROGRAM_COLUMN,
    PER_DATO_COLUMN,
    ACCEPTED_COLUMN,
    OPEN_COLUMN,
    NO_POTENTIAL_COLUMN,
    REJECTIONS_COLUMN,
    *PLACEHOLDER_COLUMNS,
    ROW_TYPE_COLUMN,
]

FACHBEREICH_ORDER = ("Gesundheit", "Sozialwesen", "Technik", "Wirtschaft")
PLACEHOLDER_VALUE = "-"


def build_bewerbungszahlen_wise_report(
    dashboard_rows: pd.DataFrame,
    previous_year_rows: pd.DataFrame | None = None,
    *,
    previous_year_final_rows: pd.DataFrame | None = None,
    program_resolver: ProgramResolver | None = None,
) -> pd.DataFrame:
    """Build status counts and prior-year comparisons for the current program selection.

    All applications are accepted plus open applications. A missing prior-year
    snapshot (None) leaves comparison fields unset; an empty snapshot counts as
    zero. Percentage changes with a zero baseline remain placeholders.
    Final rows contain fachbereich, studiengang, BEW VJ final and IMM VJ final.
    Nullable nonnegative integer counts stay missing. Forecast ratios use fractions;
    summaries use available final sums against all selected current/prior counts.
    Known aliases are resolved only for final-reference joins, not status comparisons.
    """
    if dashboard_rows.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)

    rows: list[dict[str, object]] = []
    prepared = _prepare_status_counts(dashboard_rows)
    if previous_year_rows is not None:
        prepared = _add_previous_year_counts(prepared, previous_year_rows)
    if previous_year_final_rows is not None:
        prepared = _add_final_year_counts(prepared, previous_year_final_rows, program_resolver)
    for fachbereich in _ordered_fachbereiche(prepared):
        fachbereich_rows = prepared[prepared["fachbereich"] == fachbereich].copy()
        sorted_rows = fachbereich_rows.sort_values(by="studiengang")
        for _, row in sorted_rows.iterrows():
            rows.append(_report_row(str(row["studiengang"]), row, "Studiengang"))
        rows.append(_summary_row(_fachbereich_label(fachbereich), fachbereich_rows, "Fachbereich"))

    rows.append(_summary_row("Gesamtsumme", prepared, "Gesamtsumme"))
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def previous_year_report_date(report_date: date) -> date:
    try:
        return report_date.replace(year=report_date.year - 1)
    except ValueError:
        return report_date.replace(year=report_date.year - 1, day=28)


def _prepare_status_counts(dashboard_rows: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        dashboard_rows.groupby(["fachbereich", "studiengang", "status"], as_index=False)["anzahl"]
        .sum()
        .copy()
    )
    grouped["status_bucket"] = grouped["status"].map(_status_bucket)
    pivot = grouped.pivot_table(
        index=["fachbereich", "studiengang"],
        columns="status_bucket",
        values="anzahl",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    for column in (ACCEPTED_COLUMN, NO_POTENTIAL_COLUMN, REJECTIONS_COLUMN, "sonstige"):
        if column not in pivot:
            pivot[column] = 0

    pivot[OPEN_COLUMN] = pivot["sonstige"].astype(int)
    pivot[PER_DATO_COLUMN] = pivot[ACCEPTED_COLUMN].astype(int) + pivot[OPEN_COLUMN].astype(int)
    return cast(
        pd.DataFrame,
        pivot[
            [
                "fachbereich",
                "studiengang",
                PER_DATO_COLUMN,
                ACCEPTED_COLUMN,
                OPEN_COLUMN,
                NO_POTENTIAL_COLUMN,
                REJECTIONS_COLUMN,
            ]
        ].copy(),
    )


def _status_bucket(status: object) -> str:
    normalized = str(status).strip().lower()
    if normalized == "akzeptiert":
        return ACCEPTED_COLUMN
    if normalized == "kein potential":
        return NO_POTENTIAL_COLUMN
    if normalized == "absage":
        return REJECTIONS_COLUMN
    return "sonstige"


def _add_previous_year_counts(
    current_rows: pd.DataFrame, previous_year_rows: pd.DataFrame
) -> pd.DataFrame:
    previous_columns = {current: previous for current, previous, _, _ in PREVIOUS_YEAR_COMPARISONS}
    if previous_year_rows.empty:
        with_previous_year = current_rows.copy()
        for column in previous_columns.values():
            with_previous_year[column] = 0
        return with_previous_year

    previous_year = _prepare_status_counts(previous_year_rows)[
        ["fachbereich", "studiengang", *previous_columns]
    ].rename(columns=previous_columns)
    merged = current_rows.merge(
        previous_year,
        on=["fachbereich", "studiengang"],
        how="left",
    )
    for column in previous_columns.values():
        merged[column] = merged[column].fillna(0).astype(int)
    return merged


def _ordered_fachbereiche(rows: pd.DataFrame) -> list[str]:
    values = [str(value) for value in rows["fachbereich"].drop_duplicates().tolist()]
    ordered_known = [fachbereich for fachbereich in FACHBEREICH_ORDER if fachbereich in values]
    ordered_unknown = sorted(value for value in values if value not in FACHBEREICH_ORDER)
    return ordered_known + ordered_unknown


def _fachbereich_label(fachbereich: str) -> str:
    if fachbereich == "Gesundheit":
        return "Bereich Gesundheit"
    return f"Fachbereich {fachbereich}"


def _report_row(label: str, source: pd.Series, row_type: str) -> dict[str, object]:
    row = _base_report_row(label, row_type)
    for column in (
        PER_DATO_COLUMN,
        ACCEPTED_COLUMN,
        OPEN_COLUMN,
        NO_POTENTIAL_COLUMN,
        REJECTIONS_COLUMN,
    ):
        row[column] = int(source[column])
    _set_previous_year_comparisons(row, source)
    _set_forecasts(row, source)
    return row


def _summary_row(label: str, source: pd.DataFrame, row_type: str) -> dict[str, object]:
    return _report_row(label, source.sum(numeric_only=True, min_count=1), row_type)


def _add_final_year_counts(
    current: pd.DataFrame, final: pd.DataFrame, resolver: ProgramResolver | None
) -> pd.DataFrame:
    counts = (FINAL_APPLICATIONS_COLUMN, FINAL_ENROLLMENTS_COLUMN)
    if final.empty:
        prepared = current.copy()
        for column in counts:
            prepared[column] = pd.array([None] * len(prepared), dtype="Int64")
        return prepared
    required = ["fachbereich", "studiengang", *counts]
    missing = [column for column in required if column not in final]
    if missing:
        raise ValueError(f"Erforderliche Referenzspalten fehlen: {', '.join(missing)}")
    references = final[required].copy()
    prepared = current.copy()
    for frame in (prepared, references):
        frame["__reference_program"] = frame["studiengang"].map(
            resolver.canonical_name if resolver else lambda name: str(name).strip()
        )
        if frame.duplicated(["fachbereich", "__reference_program"]).any():
            raise ValueError("Mehrdeutige Studiengangszuordnung für finale Semesterzahlen.")
    for column in counts:
        normalized: list[int | None] = []
        for value in references[column]:
            if pd.isna(value):
                normalized.append(None)
            elif (
                isinstance(value, Real)
                and not isinstance(value, bool)
                and 0 <= float(value) <= 2_147_483_647
                and float(value).is_integer()
            ):
                normalized.append(int(float(value)))
            else:
                raise ValueError(f"Ungültige finale Semesterzahl in {column}: {value}")
        references[column] = pd.array(normalized, dtype="Int64")
    return prepared.merge(
        references[["fachbereich", "__reference_program", *counts]],
        on=["fachbereich", "__reference_program"],
        how="left",
        validate="one_to_one",
    )


def _set_forecasts(row: dict[str, object], source: pd.Series) -> None:
    final_applications = _optional_number(source, FINAL_APPLICATIONS_COLUMN)
    final_enrollments = _optional_number(source, FINAL_ENROLLMENTS_COLUMN)
    if final_applications is not None:
        row[FINAL_APPLICATIONS_COLUMN] = int(final_applications)
    if final_enrollments is not None:
        row[FINAL_ENROLLMENTS_COLUMN] = int(final_enrollments)
    if final_applications is None or final_applications == 0:
        return
    if final_enrollments is not None:
        row[CONVERSION_COLUMN] = final_enrollments / final_applications
    previous = _optional_number(source, APPLICATIONS_PREVIOUS_YEAR_COLUMN)
    if previous is None:
        return
    completion = previous / final_applications
    row[COMPLETION_COLUMN] = completion
    if completion == 0:
        return
    forecast = float(source[PER_DATO_COLUMN]) / completion
    row[FORECAST_APPLICATIONS_COLUMN] = forecast
    if final_enrollments is not None:
        row[FORECAST_ENROLLMENTS_COLUMN] = forecast * (final_enrollments / final_applications)


def _optional_number(source: pd.Series, column: str) -> float | None:
    value = source.get(column)
    return None if value is None or pd.isna(value) else float(value)


def forecast_reference_warnings(report: pd.DataFrame) -> list[str]:
    """Describe missing program references and inconsistent counts for report users."""
    warnings: list[str] = []
    for _, row in report.iterrows():
        label = str(row[PROGRAM_COLUMN])
        final_bew = row[FINAL_APPLICATIONS_COLUMN]
        final_imm = row[FINAL_ENROLLMENTS_COLUMN]
        if row[ROW_TYPE_COLUMN] == "Studiengang":
            missing = [
                metric
                for metric, value in (("BEW", final_bew), ("IMM", final_imm))
                if value == PLACEHOLDER_VALUE
            ]
            if missing:
                warnings.append(f"{label}: Finale {' und '.join(missing)} fehlen.")
        previous = row[APPLICATIONS_PREVIOUS_YEAR_COLUMN]
        if isinstance(final_bew, Real):
            if isinstance(final_imm, Real) and final_imm > final_bew:
                warnings.append(f"{label}: Finale IMM übersteigen finale BEW.")
            if isinstance(previous, Real) and previous > final_bew:
                warnings.append(f"{label}: BEW am Vorjahresstichtag übersteigen finale BEW.")
    return warnings


def _set_previous_year_comparisons(row: dict[str, object], source: pd.Series) -> None:
    for current_column, previous_column, delta_column, percent_column in PREVIOUS_YEAR_COMPARISONS:
        if previous_column not in source:
            continue
        previous = int(source[previous_column])
        delta = int(source[current_column]) - previous
        row[previous_column] = previous
        row[delta_column] = delta
        row[percent_column] = delta / previous * 100 if previous else PLACEHOLDER_VALUE


def _base_report_row(label: str, row_type: str) -> dict[str, object]:
    row: dict[str, object] = {
        PROGRAM_COLUMN: label,
        ROW_TYPE_COLUMN: row_type,
    }
    for column in PLACEHOLDER_COLUMNS:
        row[column] = PLACEHOLDER_VALUE
    return row
