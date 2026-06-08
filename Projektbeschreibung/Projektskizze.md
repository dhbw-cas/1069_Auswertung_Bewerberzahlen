# Projektbeschreibung: Automatisierte Auswertung von Bewerberzahlen mit Streamlit

## Ziel des Projekts

Ziel ist es, eine Streamlit-basierte Python-Anwendung zu entwickeln, die die Auswertung von Bewerberzahlen einer Hochschule automatisiert.

Das Projekt wird in zwei Phasen unterteilt:

- **Phase 1:** Entwicklung eines Importeurs zur Datenaufbereitung  
- **Phase 2:** Aufbau einer Datenbasis und Durchführung historischer Auswertungen

---

## Architektur

- **Programmiersprache:** Python  
- **Frontend:** Streamlit  
- **Datenquelle:** Excel-Dateien  
- **Datenpfad (Entwicklung):** `data/development`
- **Persistenz:** PostgreSQL auf Sliplane  
- **Deployment:** Sliplane mit privaten Streamlit-Services und öffentlichen Basic-Auth-Proxys

### Aktuelle Zielarchitektur

Die Anwendung wird aus einer gemeinsamen Codebasis als zwei getrennte Streamlit-Services betrieben:

- **Admin-App:** `src/app.py`  
  Enthält die Seiten `Import`, `Datenstandverwaltung` und `Dashboard`.
- **Dashboard-only-App:** `src/dashboard_app.py`  
  Enthält ausschließlich die Dashboard-Seite für die Hochschulleitung.

Beide Services verwenden denselben `Dockerfile`. Der aktive Einstiegspunkt wird über `STREAMLIT_ENTRYPOINT` gesetzt.

Sliplane-Services:

- **PostgreSQL:** privater TCP-Service mit persistentem Volume.
- **Admin-Streamlit:** privater HTTP-Service mit `STREAMLIT_ENTRYPOINT=src/app.py`.
- **Dashboard-Streamlit:** privater HTTP-Service mit `STREAMLIT_ENTRYPOINT=src/dashboard_app.py`.
- **Admin-Basic-Auth-Proxy:** öffentlicher HTTP-Service vor der Admin-App.
- **Dashboard-Basic-Auth-Proxy:** öffentlicher HTTP-Service vor der Dashboard-only-App, gemeinsamer Benutzer `dashboard`.

Secrets und Konfiguration:

- `DATABASE_URL`: Verbindung zur privaten PostgreSQL-Datenbank.
- `IMPORT_DELETE_PASSWORD`: nur in der Admin-App gesetzt; aktiviert das Löschen gespeicherter Importe.
- `STREAMLIT_ENTRYPOINT`: steuert, ob Admin-App oder Dashboard-only-App gestartet wird.

Code-Struktur:

- `src/app_pages/import_page.py`: Upload, Bereinigung, Download und Import in PostgreSQL.
- `src/app_pages/data_management_page.py`: Import-Historie und passwortgeschütztes Löschen.
- `src/app_pages/dashboard_page.py`: Berichte über historische Snapshots.
- `src/bewerberzahlen/pipeline.py`: fachliche Bereinigungslogik.
- `src/bewerberzahlen/storage.py`: PostgreSQL-Schema, Speicherung, Historie, Löschen und Dashboard-Abfragen.
- `src/bewerberzahlen/app_config.py`: Umgebungsvariablen und Streamlit-Secrets.

Datenhaltung:

- Es werden nur bereinigte Daten ohne personenbezogene Felder gespeichert.
- Jeder Import erzeugt einen Eintrag in `import_batches` und zugehörige Zeilen in `applications`.
- Doppelte Importe werden über einen Hash des bereinigten Datenbestands verhindert.
- Das `snapshot_date` stammt aus dem Dateinamen und ist die Zeitachse der Berichte.

---

## Phase 1: Importeur und Datenbereinigung

### 1. Datenimport

- Die Anwendung liest Excel-Dateien ein über ein Uploadfeld
- eine typische Datei dazu liegt in `data/development/Export_110526.csv`.
- Die Struktur der Datei entspricht dem typischen Format eingehender Bewerberdaten.

---

### 2. Dublettenprüfung

- Jede Zeile repräsentiert eine Bewerbung.
- Die **E-Mail-Adresse befindet sich in der letzten Spalte**.
- Eine Dublette liegt vor, wenn:
  - dieselbe E-Mail-Adresse mehrfach vorkommt  
  - **UND** es sich um denselben Studiengang handelt
- Ausnahme:
  - Gleiche E-Mail-Adresse bei **unterschiedlichen Studiengängen** → **keine Dublette**
- Wenn Dubletten vorliegen, soll der Benutzer wählen können, welche Duplette gelöscht werden soll.
---

### 3. Statusprüfung

- Der Status befindet sich in **Spalte B**.
- Es muss geprüft werden, ob Einträge in folgenden Spalten vorhanden sind:
  - Spalte D  -> ist ein Datumseintrag vorhanden, wird der Status in B auf "Akzeptiert" gesetzt
  - Spalte F  -> ist ein Datumseintrag vorhanden, wird der Status in B auf "Absage" gesetzt
  - Spalte G  -> ist eine "1" vorhanden, wird der Status in B auf "Kein Potential" gesetzt

---

### 4. Fachbereich-Zuordnung

- Der Fachbereich wird in **Spalte H** eingetragen.
- Der Studiengang steht in **Spalte I**.
- Jeder Studiengang muss genau einem der folgenden Fachbereiche zugeordnet werden:

  - Wirtschaft  
  - Sozialwesen  
  - Gesundheit  
  - Technik  

- Die Zuordnung erfolgt regelbasiert anhand des Studiengangs.
Wir sollten dazu ein JSON aufbauen, was alle Studiengänge vorhält.
#### Studiengangs-JSON:
Studiengang {
  aktueller Name,
  alter Name,
  Fachbereich
}
---

### 5. Bereinigung personenbezogener Daten
Die Spalten L, M, N, P, R, S sollen anschliessend gelöscht werden.
### 6. Rückgabe
Die so bereinigte und aufbereitete Datei soll als Download angeboten werden

## Phase 2: Historische Auswertungen

In der zweiten Phase wird auf den bereinigten Daten aufgebaut:
Diese Daten werden in PostgreSQL gespeichert unter Ergänzung eines Datumsstempels aus dem Dateinamen, um einen historischen Datenbestand aufzubauen.
- Aufbau einer **persistenten Datenbasis**
- Durchführung von **Zeitreihenanalysen**
- Ermöglichung von **historischen Vergleichen** (z. B. Bewerberzahlen pro Zeitraum, Studiengang, Fachbereich)
- Bereitstellung eines geschützten Dashboard-only-Zugangs für die Hochschulleitung

---

## Zielbild

Am Ende entsteht eine Streamlit-Anwendung, die:

- Rohdaten automatisiert bereinigt  
- konsistente Daten erzeugt  
- und darauf aufbauend aussagekräftige Auswertungen und Vergleiche ermöglicht
