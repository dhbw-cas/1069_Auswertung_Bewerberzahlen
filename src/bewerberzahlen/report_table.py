"""Render the WiSe report as a grouped, read-only HTML table."""

from __future__ import annotations

from html import escape
from numbers import Real

import pandas as pd

from bewerberzahlen.reports import (
    ACCEPTED_COLUMN,
    ACCEPTED_DELTA_COLUMN,
    ACCEPTED_DELTA_PERCENT_COLUMN,
    ACCEPTED_PREVIOUS_YEAR_COLUMN,
    APPLICATIONS_DELTA_COLUMN,
    APPLICATIONS_DELTA_PERCENT_COLUMN,
    APPLICATIONS_PREVIOUS_YEAR_COLUMN,
    NO_POTENTIAL_COLUMN,
    OPEN_COLUMN,
    PER_DATO_COLUMN,
    PROGRAM_COLUMN,
    REJECTIONS_COLUMN,
    ROW_TYPE_COLUMN,
)

_COLUMN_GROUPS = (
    (
        "Zahlen laufende Bewerberphase",
        (PER_DATO_COLUMN, ACCEPTED_COLUMN, OPEN_COLUMN, NO_POTENTIAL_COLUMN, REJECTIONS_COLUMN),
    ),
    (
        "Vergleich akzeptierter Bewerbungen",
        (ACCEPTED_PREVIOUS_YEAR_COLUMN, ACCEPTED_DELTA_COLUMN, ACCEPTED_DELTA_PERCENT_COLUMN),
    ),
    (
        "Vergleich aller Bewerbungen",
        (
            APPLICATIONS_PREVIOUS_YEAR_COLUMN,
            APPLICATIONS_DELTA_COLUMN,
            APPLICATIONS_DELTA_PERCENT_COLUMN,
        ),
    ),
    (
        "Prognosen auf Basis der Vorjahreswerte",
        (
            "Prognose BEW",
            "Prognose IMM",
            "BEW VJ final",
            "Zielerreichung per dato/final",
            "IMM VJ final",
            "Wandlung IMM/BEW",
        ),
    ),
    (
        "Aktueller Zielwert",
        ("IMM VJ", "Zielwert", "Vergleich Zielwert", "Zielerreichung per dato"),
    ),
)
_DELTA_COLUMNS = (ACCEPTED_DELTA_COLUMN, APPLICATIONS_DELTA_COLUMN)
_DELTA_PERCENT_COLUMNS = (ACCEPTED_DELTA_PERCENT_COLUMN, APPLICATIONS_DELTA_PERCENT_COLUMN)

_TABLE_CSS = """
.wise-report {
    --background: #ffffff; --foreground: #111827; --line: #d1d5db;
    --boundary: #64748b; --group: #deebf7; --header: #f1f5f9;
    --subtotal: #d9d9d9; --total: #bfbfbf;
    --positive: #166534; --positive-background: #dcfce7;
    --negative: #991b1b; --negative-background: #fee2e2;
    max-height: 720px; box-sizing: border-box; overflow: auto; isolation: isolate;
    border: 1px solid var(--boundary); border-radius: 4px;
    color: var(--foreground); background: var(--background);
}
.wise-report.dark {
    --background: #161b22; --foreground: #f1f5f9; --line: #475569;
    --boundary: #94a3b8; --group: #253d54; --header: #222e3c;
    --subtotal: #374151; --total: #4b5563;
    --positive: #86efac; --positive-background: #143525;
    --negative: #fca5a5; --negative-background: #452323;
}
.wise-report:focus-visible { outline: 2px solid var(--boundary); outline-offset: 2px; }
.wise-report table {
    width: 2602px; min-width: 100%; table-layout: fixed;
    border-collapse: separate; border-spacing: 0; font-size: 0.875rem;
}
.wise-report .program-column { width: 250px; }
.wise-report .metric-column { width: 112px; }
.wise-report th, .wise-report td {
    padding: 6px 10px; border-right: 1px solid var(--line);
    border-bottom: 1px solid var(--line); vertical-align: middle;
    background: var(--row-background, var(--background));
}
.wise-report thead { position: sticky; top: 0; z-index: 3; }
.wise-report thead th {
    text-align: center; font-weight: 700; white-space: normal;
    overflow-wrap: anywhere; hyphens: auto; background: var(--header);
}
.wise-report thead .group-heading { background: var(--group); }
.wise-report .group-start { border-left: 2px solid var(--boundary); }
.wise-report .row-label {
    position: sticky; left: 0; z-index: 1; text-align: left;
    white-space: normal; overflow-wrap: anywhere; font-weight: 400;
}
.wise-report thead .row-label { z-index: 4; font-weight: 700; background: var(--group); }
.wise-report td { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.wise-report .per-dato { background: var(--subtotal); }
.wise-report .positive { color: var(--positive); background: var(--positive-background); }
.wise-report .negative { color: var(--negative); background: var(--negative-background); }
.wise-report .subtotal { --row-background: var(--subtotal); }
.wise-report .total { --row-background: var(--total); }
.wise-report .subtotal > *, .wise-report .total > * {
    background: var(--row-background); font-weight: 700;
    border-top: 2px solid var(--boundary);
}
.wise-report .total > * { border-top: 3px double var(--boundary); }
"""


def render_bewerbungszahlen_wise_table(
    report_rows: pd.DataFrame, *, dark_mode: bool = False
) -> str:
    """Return escaped HTML with grouped headers and fixed report row order.

    The input must contain the WiSe report columns, including its internal row
    type. It is never modified. CSS is scoped to this table; no JavaScript is used.
    """
    columns = [column for _, group in _COLUMN_GROUPS for column in group]
    required = [PROGRAM_COLUMN, *columns, ROW_TYPE_COLUMN]
    missing = [column for column in required if column not in report_rows.columns]
    if missing:
        raise ValueError(f"Erforderliche Berichtsspalten fehlen: {', '.join(missing)}")

    wrapper_class = "wise-report dark" if dark_mode else "wise-report"
    parts = [
        f"<style>{_TABLE_CSS}</style>",
        f'<div class="{wrapper_class}" role="region" tabindex="0" '
        'aria-label="Bewerbungszahlen WiSe – Berichtstabelle">',
        '<table aria-label="Bewerbungszahlen WiSe" lang="de">',
        '<colgroup><col class="program-column" />',
        '<col class="metric-column" />' * len(columns),
        "</colgroup><thead><tr>",
        f'<th class="row-label" scope="col" rowspan="2">{escape(PROGRAM_COLUMN)}</th>',
    ]
    for title, group in _COLUMN_GROUPS:
        parts.append(
            f'<th class="group-heading group-start" scope="colgroup" '
            f'colspan="{len(group)}">{escape(title)}</th>'
        )
    parts.append("</tr><tr>")
    for _, group in _COLUMN_GROUPS:
        for index, column in enumerate(group):
            css_class = ' class="group-start"' if index == 0 else ""
            parts.append(f'<th scope="col"{css_class}>{escape(column)}</th>')
    parts.append("</tr></thead><tbody>")

    group_starts = {group[0] for _, group in _COLUMN_GROUPS}
    for values in report_rows[required].itertuples(index=False, name=None):
        row_class = {"Fachbereich": "subtotal", "Gesamtsumme": "total"}.get(str(values[-1]), "")
        parts.append(f'<tr class="{row_class}">')
        parts.append(f'<th class="row-label" scope="row">{escape(str(values[0]))}</th>')
        for column, value in zip(columns, values[1:-1], strict=True):
            classes = ["group-start"] if column in group_starts else []
            if column == PER_DATO_COLUMN:
                classes.append("per-dato")
            if column in (*_DELTA_COLUMNS, *_DELTA_PERCENT_COLUMNS) and isinstance(value, Real):
                numeric_value = float(value)
                if numeric_value > 0:
                    classes.append("positive")
                elif numeric_value < 0:
                    classes.append("negative")
            parts.append(
                f'<td class="{" ".join(classes)}">{escape(_format_value(column, value))}</td>'
            )
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _format_value(column: str, value: object) -> str:
    if not isinstance(value, Real):
        return str(value)
    if column in _DELTA_PERCENT_COLUMNS:
        return f"{value:+.1f} %".replace(".", ",") if value != 0 else "0,0 %"
    if column in _DELTA_COLUMNS:
        return f"{value:+.0f}" if value != 0 else "0"
    return f"{value:.0f}"
