from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .constants import FACHBEREICHE


@dataclass(frozen=True)
class ProgramEntry:
    name: str
    fachbereich: str
    aliases: list[str]


class ProgramResolver:
    def __init__(self, programs: Iterable[ProgramEntry]):
        by_name: dict[str, ProgramEntry] = {}
        for entry in programs:
            normal_name = self._normalize(entry.name)
            by_name[normal_name] = entry
            for alias in entry.aliases:
                by_name[self._normalize(alias)] = entry
        self._by_name = by_name

    @classmethod
    def from_file(cls, path: Path) -> ProgramResolver:
        data = json.loads(path.read_text(encoding="utf-8"))
        programs: list[ProgramEntry] = []
        for raw in data.get("programs", []):
            name = raw["name"].strip()
            fachbereich = raw["fachbereich"].strip()
            aliases = [alias.strip() for alias in raw.get("aliases", [])]
            programs.append(ProgramEntry(name=name, fachbereich=fachbereich, aliases=aliases))
        return cls(programs)

    @classmethod
    def from_programs(cls, programs: Iterable[ProgramEntry]) -> ProgramResolver:
        return cls(programs)

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip()

    def canonical_name(self, program_name: str) -> str:
        """Resolve known aliases for reference joins; preserve unknown names."""
        normalized = self._normalize(program_name)
        entry = self._by_name.get(normalized)
        return entry.name if entry else normalized

    def program_names(self) -> list[str]:
        """Return unique canonical names for explicit reference import assignments."""
        return sorted({entry.name for entry in self._by_name.values()})

    def resolve(
        self, program_name: str, manual_assignments: dict[str, str] | None = None
    ) -> tuple[str | None, bool]:
        normalized = self._normalize(program_name)
        if not normalized:
            return None, False

        manual = (manual_assignments or {}).get(normalized)
        if manual:
            if manual not in FACHBEREICHE:
                raise ValueError(f"Ungültiger Fachbereich in manueller Zuordnung: {manual}")
            return manual, True

        entry = self._by_name.get(normalized)
        if entry:
            return entry.fachbereich, False
        return None, False

    def unknown_programs(
        self, program_names: Iterable[str], manual_assignments: dict[str, str] | None = None
    ) -> set[str]:
        unknown: set[str] = set()
        for name in program_names:
            normalized = self._normalize(name)
            if not normalized:
                continue
            manual = (manual_assignments or {}).get(normalized)
            if manual and manual in FACHBEREICHE:
                continue
            if normalized not in self._by_name:
                unknown.add(normalized)
        return unknown
