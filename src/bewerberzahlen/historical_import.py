from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO

import pandas as pd

from .io_utils import normalize_import_dataframe

HISTORICAL_SHEET_PATTERN = re.compile(r"Daten (?P<report_date>\d{2}\.\d{2}\.(?:\d{2}|\d{4}))")


@dataclass(frozen=True)
class HistoricalDataset:
    sheet_name: str
    report_date: date
    dataframe: pd.DataFrame


def read_historical_workbook_from_bytes(content: bytes, filename: str) -> list[HistoricalDataset]:
    """Read and normalize all dated data sheets from a historical XLSX workbook."""
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Bitte eine XLSX-Datei mit historischen Datenbeständen hochladen.")
    if not content:
        raise ValueError("Die hochgeladene XLSX-Datei ist leer.")

    workbook = pd.ExcelFile(BytesIO(content))
    datasets: list[HistoricalDataset] = []
    sheet_by_report_date: dict[date, str] = {}

    for raw_sheet_name in workbook.sheet_names:
        sheet_name = str(raw_sheet_name)
        match = HISTORICAL_SHEET_PATTERN.fullmatch(sheet_name.strip())
        if match is None:
            continue

        report_date = _parse_report_date(match.group("report_date"))
        existing_sheet = sheet_by_report_date.get(report_date)
        if existing_sheet is not None:
            raise ValueError(
                f"Der Stichtag {report_date:%d.%m.%Y} kommt mehrfach vor: "
                f'"{existing_sheet}" und "{sheet_name}".'
            )

        dataframe = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
            dtype=str,
            keep_default_na=False,
        )
        dataframe = dataframe.loc[
            :,
            [not str(column).startswith("Unnamed:") for column in dataframe.columns],
        ]
        dataframe = (
            dataframe.replace(r"^\s*$", pd.NA, regex=True)
            .dropna(axis=0, how="all")
            .fillna("")
            .reset_index(drop=True)
        )
        dataframe = normalize_import_dataframe(dataframe)

        datasets.append(
            HistoricalDataset(
                sheet_name=sheet_name,
                report_date=report_date,
                dataframe=dataframe,
            )
        )
        sheet_by_report_date[report_date] = sheet_name

    if not datasets:
        raise ValueError(
            'Keine Datenreiter gefunden. Erwartet werden Reiter wie "Daten 15.12.2025".'
        )

    return sorted(datasets, key=lambda dataset: dataset.report_date)


def _parse_report_date(value: str) -> date:
    date_format = "%d.%m.%Y" if len(value.rsplit(".", maxsplit=1)[-1]) == 4 else "%d.%m.%y"
    try:
        return datetime.strptime(value, date_format).date()
    except ValueError as exc:
        raise ValueError(f"Ungültiger Stichtag im Datenreiter: {value}") from exc
