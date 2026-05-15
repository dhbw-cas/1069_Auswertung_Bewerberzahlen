from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .constants import (
    ACCEPTED_COLUMN,
    DERIVED_STATUS_VALUES,
    EMAIL_COLUMN,
    FACHBEREICH_COLUMN,
    NO_POTENTIAL_COLUMN,
    PII_COLUMNS,
    PROGRAM_COLUMN,
    REJECTION_COLUMN,
    REQUIRED_COLUMNS,
    STATUS_COLUMN,
)
from .mapping import ProgramResolver
from .report import Issue, ProcessingResult


@dataclass
class PipelineConfig:
    manual_assignments: dict[str, str] | None = None
    duplicate_keep_rows: set[int] | None = None


def process_dataframe(
    df: pd.DataFrame, resolver: ProgramResolver, config: PipelineConfig | None = None
) -> ProcessingResult:
    cfg = config or PipelineConfig()
    working = df.copy()
    n_input = len(working)
    working["__row_number"] = range(2, len(working) + 2)
    warnings: list[Issue] = []
    errors: list[Issue] = []

    missing = _missing_columns(working.columns)
    if missing:
        errors.append(
            Issue(
                message=f"Erforderliche Spalten fehlen: {', '.join(sorted(missing))}", level="error"
            )
        )
        return ProcessingResult(
            cleaned=None, warnings=warnings, errors=errors, duplicates=pd.DataFrame()
        )

    _normalize_columns(working)

    duplicate_groups = _build_duplicate_groups(working)
    duplicates = pd.DataFrame()
    duplicates_resolved = True
    if duplicate_groups:
        duplicates, working, unresolved_groups = _resolve_duplicates_by_selection(
            working,
            duplicate_groups,
            cfg.duplicate_keep_rows,
        )
        duplicates_resolved = not unresolved_groups
        if unresolved_groups:
            unresolved_rows = [row for group in unresolved_groups for row in group]
            warnings.append(
                Issue(
                    message=(
                        "Dubletten gefunden (gleiche E-Mail + Studiengang). "
                        "Bitte pro Gruppe genau einen Eintrag zum Behalten auswählen."
                    ),
                    level="warning",
                    rows=unresolved_rows,
                    context={"anzahl_gruppen": len(unresolved_groups)},
                )
            )
        elif not duplicates.empty:
            warnings.append(
                Issue(
                    message="Dubletten wurden gemäß Auswahl entfernt.",
                    level="warning",
                    rows=_row_numbers(duplicates),
                    context={"anzahl": len(duplicates)},
                )
            )

    missing_programs, working = _separate_missing_programs(working)
    if not missing_programs.empty:
        warnings.append(
            Issue(
                message="Studiengang fehlt; Zeile wurde ignoriert.",
                level="warning",
                rows=_row_numbers(missing_programs),
                context={"anzahl": len(missing_programs)},
            )
        )

    _apply_status_rules(working)

    mapping_errors = _apply_fachbereich_mapping(working, resolver, cfg.manual_assignments)
    if mapping_errors:
        for program, rows in sorted(mapping_errors.items()):
            errors.append(
                Issue(
                    message=f"Unbekannter Studiengang: {program}",
                    level="error",
                    rows=rows,
                )
            )

    cleaned: pd.DataFrame | None = None
    if not errors and duplicates_resolved:
        cleaned = _finalize_output(working)

    duplicates = _sanitize_output(duplicates)

    n_unknown_program = sum(len(rows) for rows in mapping_errors.values())
    n_kept = len(cleaned) if cleaned is not None else 0

    return ProcessingResult(
        cleaned=cleaned,
        warnings=warnings,
        errors=errors,
        duplicates=duplicates,
        duplicate_groups=[list(group) for group in duplicate_groups.values()],
        n_input=n_input,
        n_kept=n_kept,
        n_duplicates=_count_duplicate_excess(duplicate_groups),
        n_missing_program=len(missing_programs),
        n_unknown_program=n_unknown_program,
    )


def _missing_columns(columns: Iterable[str]) -> set[str]:
    return {col for col in REQUIRED_COLUMNS if col not in columns}


def _normalize_columns(df: pd.DataFrame) -> None:
    df[EMAIL_COLUMN] = df[EMAIL_COLUMN].astype(str).str.strip().str.lower()
    df[PROGRAM_COLUMN] = df[PROGRAM_COLUMN].astype(str).str.strip()
    df[STATUS_COLUMN] = df[STATUS_COLUMN].fillna("").astype(str)
    # Stelle sicher, dass Fachbereich beschreibbar ist (kein float64-Spaltentyp aus Excel)
    df[FACHBEREICH_COLUMN] = df[FACHBEREICH_COLUMN].astype("string")


def _build_duplicate_groups(df: pd.DataFrame) -> dict[tuple[str, str], list[int]]:
    grouped: dict[tuple[str, str], list[int]] = {}
    for _, group in df.groupby([PROGRAM_COLUMN, EMAIL_COLUMN], sort=False, dropna=False):
        if len(group) <= 1:
            continue
        program = str(group[PROGRAM_COLUMN].iloc[0])
        email = str(group[EMAIL_COLUMN].iloc[0])
        row_numbers = sorted(_row_numbers(group))
        grouped[(program, email)] = row_numbers
    return grouped


def _resolve_duplicates_by_selection(
    df: pd.DataFrame,
    duplicate_groups: dict[tuple[str, str], list[int]],
    selected_rows: set[int] | None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[list[int]]]:
    selected = selected_rows or set()
    unresolved_groups: list[list[int]] = []
    rows_to_remove: set[int] = set()

    for rows in duplicate_groups.values():
        chosen = [row for row in rows if row in selected]
        if len(chosen) != 1:
            unresolved_groups.append(rows)
            continue
        selected_row = chosen[0]
        rows_to_remove.update(row for row in rows if row != selected_row)

    duplicate_rows = {row for rows in duplicate_groups.values() for row in rows}
    row_numbers = pd.Series(df["__row_number"], index=df.index, dtype="int64")
    if unresolved_groups:
        mask = row_numbers.isin(duplicate_rows)
        duplicates = df.loc[mask, :].copy()
        return duplicates, df, unresolved_groups

    remove_mask = row_numbers.isin(rows_to_remove)
    duplicates = df.loc[remove_mask, :].copy()
    deduped = df.loc[~remove_mask, :].copy()
    return duplicates, deduped, []


def _count_duplicate_excess(duplicate_groups: dict[tuple[str, str], list[int]]) -> int:
    return sum(max(len(rows) - 1, 0) for rows in duplicate_groups.values())


def _separate_missing_programs(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    program_values = pd.Series(df[PROGRAM_COLUMN], index=df.index)
    mask_missing = ~program_values.apply(_has_value).astype(bool)
    missing = df.loc[mask_missing, :].copy()
    present = df.loc[~mask_missing, :].copy()
    return missing, present


def _row_numbers(df: pd.DataFrame) -> list[int]:
    return [int(value) for value in df["__row_number"].tolist()]


def _has_value(value: object) -> bool:
    value_any: Any = value
    if pd.isna(value_any):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _apply_status_rules(df: pd.DataFrame) -> None:
    priority = [
        (REJECTION_COLUMN, DERIVED_STATUS_VALUES[REJECTION_COLUMN]),
        (ACCEPTED_COLUMN, DERIVED_STATUS_VALUES[ACCEPTED_COLUMN]),
        (NO_POTENTIAL_COLUMN, DERIVED_STATUS_VALUES[NO_POTENTIAL_COLUMN]),
    ]

    for idx, row in df.iterrows():
        chosen: str | None = None
        for col, status_value in priority:
            if _has_value(row[col]) and not (
                col == NO_POTENTIAL_COLUMN and str(row[col]).strip() == "0"
            ):
                chosen = status_value
                break
        if chosen:
            df.at[idx, STATUS_COLUMN] = chosen


def _apply_fachbereich_mapping(
    df: pd.DataFrame, resolver: ProgramResolver, manual_assignments: dict[str, str] | None
) -> dict[str, list[int]]:
    errors: dict[str, list[int]] = {}
    for idx, row in df.iterrows():
        program_name = str(row[PROGRAM_COLUMN])
        row_number = int(row["__row_number"])
        fachbereich, _ = resolver.resolve(program_name, manual_assignments)
        if fachbereich:
            df.at[idx, FACHBEREICH_COLUMN] = fachbereich
        else:
            errors.setdefault(program_name, []).append(row_number)
    return errors


def _finalize_output(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = _remove_pii(df)
    return _drop_internal_columns(df)


def _sanitize_output(df: pd.DataFrame) -> pd.DataFrame:
    df = _remove_pii(df.copy())
    return _drop_internal_columns(df)


def _remove_pii(df: pd.DataFrame) -> pd.DataFrame:
    df.drop(columns=[col for col in PII_COLUMNS if col in df.columns], inplace=True)
    return df


def _drop_internal_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in df.columns if c.startswith("__")], errors="ignore")
