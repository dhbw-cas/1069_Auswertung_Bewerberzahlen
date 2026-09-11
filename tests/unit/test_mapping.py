from pathlib import Path

from bewerberzahlen.mapping import ProgramResolver

MAPPING_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "data" / "mapping" / "studiengaenge.json"
)


def test_igtc_mba_ist_eigenstaendiger_studiengang_der_wirtschaft() -> None:
    resolver = ProgramResolver.from_file(MAPPING_PATH)

    assert resolver.resolve("IGTC MBA") == ("Wirtschaft", False)
    assert resolver.unknown_programs(["IGTC MBA"]) == set()
