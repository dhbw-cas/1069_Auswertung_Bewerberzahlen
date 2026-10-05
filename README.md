# Auswertung Bewerberzahlen

Streamlit-Anwendung zur Bereinigung und historischen Auswertung von Bewerberzahlen.

## Aktueller Stand

- Phase 1: CSV-Upload, Bereinigung, Dublettenentscheidung, Statusableitung, Fachbereich-Zuordnung und Excel-Download.
- Phase 2: Bereinigte Daten können in PostgreSQL gespeichert werden.
- Historische XLSX-Datenbasen können über ihre Reiter `Daten dd.mm.yyyy` stapelweise importiert werden.
- Finale BEW- und IMM-Semesterzahlen können separat importiert und für Prognosen genutzt werden.
- Produktivbetrieb über Sliplane mit getrenntem Admin- und Dashboard-Zugang.

## Architekturüberblick

Die Anwendung besteht aus einer gemeinsamen Codebasis mit zwei Streamlit-Einstiegspunkten:

- `src/app.py`: Admin-App mit den Seiten `Import`, `Altbestände`, `Datenstandverwaltung` und `Dashboard`.
- `src/dashboard_app.py`: Dashboard-only-App für die Hochschulleitung.

Die Seiten liegen unter `src/app_pages/`:

- `import_page.py`: CSV-Upload, Bereinigung, Download und Speichern in PostgreSQL.
- `historical_import_page.py`: XLSX-Upload historischer Datenreiter, Aufbereitung und stapelweiser Import.
- `data_management_page.py`: Import-Historie und passwortgeschütztes Löschen gespeicherter Importe.
- `dashboard_page.py`: Berichte, Filter, Kennzahlen und Diagramme über Datenbestände.

Die fachliche Logik liegt in `src/bewerberzahlen/`:

- `pipeline.py`: Bereinigung, Dublettenlogik, Statusableitung und Fachbereich-Zuordnung.
- `historical_import.py`: Erkennung, Datumsableitung und Normalisierung historischer XLSX-Datenreiter.
- `reference_import.py`: Validierung und Zuordnung finaler BEW-/IMM-Semesterzahlen aus XLSX.
- `reference_storage.py`: unabhängige, transaktionale Speicherung der Semesterreferenzen.
- `storage.py`: PostgreSQL-Schema, Import-Speicherung, Import-Historie, Löschen und Dashboard-Abfragen.
- `mapping.py`: Studiengang-zu-Fachbereich-Auflösung.
- `app_config.py`: Zugriff auf Umgebungsvariablen und Streamlit-Secrets.

PostgreSQL speichert nur bereinigte Daten ohne personenbezogene Felder. Beim Speichern wird ein Berichtsdatum ausgewählt; pro Berichtsdatum existiert höchstens ein Datenbestand. Ein vorhandener Datenbestand wird nur nach expliziter Bestätigung ersetzt.

Beim Altbestandsimport wird jeder erkannte Stichtag einzeln gespeichert. Bereits vorhandene Datenbestände mit demselben Stichtag werden dabei automatisch ersetzt; ein Fehler bei einem Reiter verhindert nicht das Speichern anderer Reiter.

## Semesterreferenzen und Prognosen

Unter **Altbestände → Importart → Semesterreferenzen (BEW / IMM)** können finale Zahlen aus
einer Berichtsdatei importiert werden. BEW und IMM lassen sich unabhängig auswählen:

- **BEW:** ausschließlich die Spalten `BEW WiSe…` und `BEW SoSe…` im Reiter
  `Entwicklung Conversion BEW-IMMA`. Die BEW-Finalspalten anderer Berichtsreiter werden
  nicht verwendet, da sie in der vorhandenen Datei abweichende Zahlen enthalten.
- **IMM:** ausschließlich die Spalten `WiSe…` und `SoSe…` im Reiter
  `Entwicklung Imma je Studienjahr`. Die Conversion- und Studienjahressummen werden nicht übernommen.

Leere Zellen bleiben fehlend, explizite Nullen werden gespeichert. Bereichs- und Gesamtsummen
werden ignoriert. Formelzellen, negative oder nicht ganzzahlige Zahlen, doppelte Semester
und doppelte Schlüssel nach der Studiengangszuordnung verhindern das Speichern.
Zweistellige Semesterjahre werden als 2000–2099 interpretiert; vierstellige Jahre werden ebenfalls unterstützt.

Nach der Semester-Auswahl müssen die Studiengangsnamen geprüft werden. Bekannte Namen/Aliase
werden vorgeschlagen. Historische Namen können einem heutigen Studiengang oder einem
eigenständigen historischen Studiengang mit Fachbereich zugeordnet werden. Die Vorschau zeigt
die neuen Werte, vorhandene Werte und Quellzellen. Speichern erfordert eine explizite Bestätigung
und bei vorhandenen Zahlen zusätzlich die Ersetzungsbestätigung.

Die Tabellen `semester_application_totals` und `semester_enrollment_totals` werden additiv
und wiederholbar angelegt. Je Semester, Fachbereich und Studiengang wird eine nichtnegative
Ganzzahl mit Quelldatei, Reiter, Zelle, Importeur und Importzeit gespeichert.
Ein Speichervorgang wird vollständig transaktional durchgeführt. Eine zwischen Vorschau
und Speichern veränderte Datenbasis verlangt eine neue Prüfung. Andere Schlüssel, leere
Quellzellen und die jeweils andere Referenzart bleiben unberührt. Das Löschen oder Ersetzen
von Bewerbungsdatenständen löscht keine Semesterreferenzen.

Im Bericht **Bewerbungszahlen WiSe** ist das Zielsemester als Wintersemester-Startjahr
auswählbar und mit dem Berichtsjahr vorbelegt. Für WiSe26/27 werden die Finalzahlen aus
WiSe25/26 geladen. Der Vorjahresstichtag wird unabhängig davon exakt ein Jahr zurückversetzt,
z. B. 15.07.2026 → 15.07.2025; der 29. Februar wird im Vorjahr zum 28. Februar.
Die alten zeitlichen Semesterregeln werden für diese Zuordnung nicht verwendet.

Mit **B** = aktuelle Bewerbungen, **V** = Bewerbungen am Vorjahresstichtag,
**F** = finale Vorjahresbewerbungen und **I** = finale Vorjahresimmatrikulationen gilt:

| Spalte | Berechnung |
| --- | --- |
| BEW VJ final | F |
| IMM VJ final | I |
| Zielerreichung per dato/final | V / F |
| Prognose BEW | B / (V / F) |
| Wandlung IMM/BEW | I / F |
| Prognose IMM | Prognose BEW × (I / F) |

„Bewerbungen“ entspricht weiterhin **akzeptiert + offen**, ohne Absagen und „Kein Potential“.
Die Wandlung ist der Anteil der Immatrikulierten, nicht der Anteil der Nicht-Immatrikulierten.
Intern bleiben Prognosen ungerundet und Quoten werden als Bruchwerte berechnet. Die Tabelle zeigt
Prognosen als ganze Zahlen und Quoten mit einer Nachkommastelle in Prozent.
Beispiel: B = 120, V = 80, F = 200 und I = 150 ergibt 40 %, 300 BEW, 75 % Wandlung und 225 IMM.

Fehlende Eingangsgrößen und Nullnenner ergeben für die abhängige Metrik `-`.
Verfügbare Finalzahlen und unabhängig berechenbare Quoten bleiben sichtbar.
Bekannte Aliase werden für die Finalreferenzen aufgelöst; bisherige Status- und Delta-Vergleiche
werden dadurch nicht verändert. Mehrdeutige Zuordnungen verhindern eine doppelte Zählung.

Fachbereichs- und Gesamtprognosen werden aus den Grundsummen neu berechnet, nicht aus
Einzelprognosen oder gemittelten Quoten. Dabei werden alle ausgewählten aktuellen und
Vorjahresbewerbungen, aber nur vorhandene finale Referenzen summiert. Fehlen Referenzen,
kennzeichnet ein Hinweis diese **Teilbasis** mit den betroffenen Studiengängen;
die Summenprognose kann dadurch verzerrt sein. Ohne irgendeinen Wert einer Referenzgröße
bleibt ihre Summe fehlend. Quoten über 100 % werden nicht begrenzt; widersprüchliche
BEW-/IMM-Zahlen werden mit einem Hinweis angezeigt.

Der neue Import wird im Admin-Zugang angeboten, der Dashboard-Zugang liest die gespeicherten
Referenzen für die Prognosen. Die lokale Excel-Quelldatei bleibt unverändert und außerhalb von Git.
Nach dem Deployment müssen die gewünschten Finalzahlen über den Admin-Import gespeichert werden.

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
