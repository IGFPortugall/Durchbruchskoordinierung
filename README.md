# Durchbruchskoordinierung

Architektur, Tragwerksplanung und TGA/ELT/Labor-Planer stimmen Durchbrüche (und andere Bauteile)
miteinander ab, kommentieren und geben sie frei – in Revit (pyRevit) oder im Browser.
Ohne zentralen Server: jede Partei schreibt ihre Daten in einen gemeinsamen Ordner.

- Konzept: [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md)
- Datenformat: [docs/DATENFORMAT.md](docs/DATENFORMAT.md)

## Aufbau

| Ordner | Inhalt |
|---|---|
| `src/dbk_core/` | Kern: Ereignisse lesen/schreiben, Pflicht-Regeln, Status-Berechnung. Python 2.7 (IronPython/pyRevit) und 3.x |
| `tests/` | Tests für den Kern |
| `web/` | Web-App mit 3D-/Grundriss-Viewer (That Open Components 3.6), ohne Build-Schritt |
| `web/app/kern.js` | Statuslogik in JavaScript – wird gegen die Python-Version geprüft (`web/test/`) |
| `werkzeuge/` | Entwicklungs-Server, Demo-Daten |

## Web-App ausprobieren

```powershell
py werkzeuge/demo_erzeugen.py
```

```powershell
py werkzeuge/devserver.py --projekt testdaten/demo
```

Dann <http://127.0.0.1:8765/> öffnen. Die Demo nutzt das Schulmodell aus den That-Open-Beispielen
und acht Beispiel-Durchbrüche.

Ohne Entwicklungs-Server fragt die App nach dem Projektordner (Chrome/Edge, File System Access API).
Dafür muss `web/` über `https://` oder `localhost` ausgeliefert werden – `file://` funktioniert nicht.

Bedienung:
- **3D / Grundriss** oben umschalten; Auswahl und Ausschnitt bleiben erhalten.
- **Geschoss** wählen: im 3D werden höhere Geschosse ausgeblendet, im Grundriss wird 1,00 m über OKFF geschnitten.
- **Schnitt setzen**: danach auf eine Fläche klicken, die Ebene am Pfeil ziehen. **Schnittbox** legt sechs
  verschiebbare Ebenen um den gewählten Durchbruch.
- Liste links (Standard: „Wartet auf mich“), Details mit Freigaben, Verlauf und Chat rechts.
- Neue Einträge anderer Parteien erscheinen automatisch (alle 5 Sekunden).

## Revit (pyRevit-Reiter „DBK“)

Die Erweiterung liegt in `pyrevit/DBK.extension`; der Ordner `pyrevit` ist in pyRevit als Suchpfad eingetragen.

Ein Knopf **Durchbruchskoordination** öffnet ein Werkzeug (bleibt neben Revit offen) mit Reitern – die Reiter richten sich nach der Rolle:

| Reiter | Was passiert |
|---|---|
| **Projekt** | Projektordner (legt bei Bedarf ein neues Projekt an), Name, Firma, Rolle, Modellkürzel, Ansichtsvorlagen. Nur beim ersten Mal nötig |
| **Durchbrüche** (TGA, ELT, Labor) | Links: welche Familien/Typen Durchbrüche sind. Rechts: alle Exemplare nach Ebene mit Zustand (neu, verschoben, schon geschickt, abgelehnt). **Auswahlvorlagen** (z. B. „EG Rohbau“) merken Ebene und zurückgehaltene Exemplare; neu hinzugekommene werden automatisch angehakt |
| **Modell** | Modell-Vorlagen je Partei (TGA ohne Durchbrüche, Architektur gesamt …) mit eigener Exportansicht „DBK Paket – Name“ |
| **Einreichen** / **Veröffentlichen** | Zusammenfassung, Prüfrunde, ein Knopf: Durchbrüche als Prüfobjekte, Modelle als IFC in den Viewer |

Oben: **Nächster Hinweis**, **In Revit zeigen**, **Viewer öffnen**. Prüfen, Kommentieren und Freigeben passieren im Viewer (Prüf-Manager für alle).

Grundsatz: Was in der Exportansicht sichtbar ist, geht raus. Durchbrüche werden nie ins Modell-IFC exportiert.

## Tests

```powershell
cd tests; py -m unittest -v
```

Die Tests laufen unter CPython 3 und unter IronPython 2.7 in Revit (pyRevit).
Abgleich Python ↔ JavaScript: Entwicklungs-Server starten und <http://127.0.0.1:8765/test/> öffnen.

## Stand

- [x] Kern (Python), Datenformat, Tests
- [x] Web-App: Modelle laden, Durchbrüche nach Status, 3D/Grundriss, Geschosse, Schnitte, Freigeben/Ablehnen, Chat
- [ ] pyRevit-Erweiterung (Start-Dialog, Prüfset, Einreichen, Prüf-Manager, Parameter-Sync, Modell veröffentlichen)
- [ ] IFC im Browser hochladen und als Fragments ablegen
- [ ] Plan-Ebene (PDF aus Revit) und Modus „Plan“
- [ ] Verwaltungs-Seite (Rollen, Status, Pflicht-Matrix)
- [ ] Berichte (PDF-Verlauf, BCF)
