# Auswertung Bewerberzahlen

Streamlit-Anwendung zur Bereinigung und historischen Auswertung von Bewerberzahlen.

## Aktueller Stand

- Phase 1: CSV-Upload, Bereinigung, Dublettenentscheidung, Statusableitung, Fachbereich-Zuordnung und Excel-Download.
- Phase 2: Bereinigte Daten können in PostgreSQL gespeichert werden.
- Produktivbetrieb über Sliplane mit getrenntem Admin- und Dashboard-Zugang.

## Architekturüberblick

Die Anwendung besteht aus einer gemeinsamen Codebasis mit zwei Streamlit-Einstiegspunkten:

- `src/app.py`: Admin-App mit den Seiten `Import`, `Datenstandverwaltung` und `Dashboard`.
- `src/dashboard_app.py`: Dashboard-only-App für die Hochschulleitung.

Die Seiten liegen unter `src/app_pages/`:

- `import_page.py`: CSV-Upload, Bereinigung, Download und Speichern in PostgreSQL.
- `data_management_page.py`: Import-Historie und passwortgeschütztes Löschen gespeicherter Importe.
- `dashboard_page.py`: Berichte, Filter, Kennzahlen und Diagramme über historische Snapshots.

Die fachliche Logik liegt in `src/bewerberzahlen/`:

- `pipeline.py`: Bereinigung, Dublettenlogik, Statusableitung und Fachbereich-Zuordnung.
- `storage.py`: PostgreSQL-Schema, Import-Speicherung, Import-Historie, Löschen und Dashboard-Abfragen.
- `mapping.py`: Studiengang-zu-Fachbereich-Auflösung.
- `app_config.py`: Zugriff auf Umgebungsvariablen und Streamlit-Secrets.

PostgreSQL speichert nur bereinigte Daten ohne personenbezogene Felder. Doppelte Importe werden über einen Hash des bereinigten Datenbestands verhindert.

## Lokal starten

```bash
uv run streamlit run src/app.py
```

## PostgreSQL konfigurieren

Die App liest die Datenbankverbindung aus `DATABASE_URL`.

```env
DATABASE_URL=postgresql://bewerberzahlen_app:<passwort>@<host>:5432/bewerberzahlen
IMPORT_DELETE_PASSWORD=<lösch-passwort>
```

Ohne `DATABASE_URL` funktioniert die Bereinigung weiter, aber das Speichern in die Datenbank ist deaktiviert.
Ohne `IMPORT_DELETE_PASSWORD` ist das Löschen gespeicherter Importe deaktiviert.

## Sliplane

Die produktive Zielarchitektur ist:

- Admin-Streamlit-App als privater HTTP-Service.
- Dashboard-only-Streamlit-App als privater HTTP-Service.
- PostgreSQL als privater TCP-Service mit persistentem Volume.
- Admin-Basic-Auth-Proxy als öffentlicher HTTP-Service vor der Admin-App.
- Dashboard-Basic-Auth-Proxy als öffentlicher HTTP-Service vor der Dashboard-only-App.

Der Streamlit-Service nutzt den `Dockerfile` im Repository. In Sliplane ist daher kein Override CMD nötig.
`DATABASE_URL` und `IMPORT_DELETE_PASSWORD` sollten in Sliplane als Secrets gesetzt werden.
Der Docker-Start kann über `STREAMLIT_ENTRYPOINT` gesteuert werden: `src/app.py` für die Admin-App und `src/dashboard_app.py` für die Dashboard-only-App.

Admin-Service:

```env
STREAMLIT_ENTRYPOINT=src/app.py
DATABASE_URL=postgresql://bewerberzahlen_app:<passwort>@library-postgres.internal:5432/bewerberzahlen
IMPORT_DELETE_PASSWORD=<lösch-passwort>
```

Dashboard-Service:

```env
STREAMLIT_ENTRYPOINT=src/dashboard_app.py
DATABASE_URL=postgresql://bewerberzahlen_app:<passwort>@library-postgres.internal:5432/bewerberzahlen
```

Der Dashboard-Basic-Auth-Proxy verwendet den gemeinsamen Benutzer `dashboard`.

PostgreSQL-Einrichtung: [`docs/sliplane-postgres.md`](docs/sliplane-postgres.md)

## Qualitaetschecks

```bash
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run pytest
```
