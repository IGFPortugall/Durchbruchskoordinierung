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
- **Klick auf einen Durchbruch** (Liste oder Modell): Schnittbox mit **2 m** Abstand darum (abschaltbar unter „Schnitte“).
- **Werkzeuge unten links im 3D-Fenster**:
  - **Schnitte** – „+ Schnitt“ (auf eine Fläche klicken, Ebene am Pfeil ziehen) oder „+ Box“. Jeder Schnitt hat
    einen Namen (Doppelklick: umbenennen), Box-Seiten per Regler, Ebene umdrehbar. Oben im Auswahlfeld
    zwischen den Schnitten **umschalten**; es ist immer höchstens einer aktiv.
  - **Röntgen** – Modelle blass, Durchbrüche bleiben voll sichtbar (auch im Menü „Ansicht ⚙“).
  - **Messen** – zwei Punkte anklicken (rastet auf Ecken ein): Strecke, waagerecht und senkrecht.
    Weiter messen bis Esc; „Messen“ erneut klicken löscht die Messungen.
- **Beschriftung** (Ansicht ⚙ › Darstellung): *Automatisch* zeigt Nummer · Größe für die Auswahl, unter der Maus
  und in Nahsicht – ohne Überdeckung; *Alle* oder *Aus* wählbar.
- **Seitenleiste links**: Modelle, Pläne (2D) und Durchbruch-Stände – je mit dem Auge schaltbar.
  Je Stand zeigen farbige Zahlen, wie viele in Prüfung, abgelehnt oder frei sind (Klick filtert).
  ⌖ am Modell: Kategorien, „bei mir nicht laden“ und **Ausrichten**: am genauesten **mit Punkten** – denselben
  Punkt (Gebäudeecke, Achsschnitt) erst im Modell, dann im Referenzmodell anklicken (rastet auf Ecken ein),
  zweites Punktpaar für die Drehung. Zahlen/Regler für Feinkorrekturen. Gilt zunächst nur im eigenen Browser;
  der Eigentümer des Modells kann die Lage **für alle speichern**.
- Große FBX aus Revit: Teile gleicher Kategorie und Farbe werden beim Laden zusammengelegt
  (Zehntausende Bauteile → wenige Dutzend Körper); angeklickte Bauteile zeigen trotzdem ihre Revit-Eigenschaften.
  Beim ersten Öffnen legt der Viewer daneben eine kompakte Fassung `<Hash>.dbkg` ab (etwa ein Zehntel der
  Größe); alle späteren Öffnungen laden in Sekunden.
- **+ Modell laden** (gestricheltes Feld unten links): IFC oder FBX anklicken oder hineinziehen – liegt danach für alle im Projektordner.
- Rechts die Durchbruch-Liste (Standard: „Wartet auf mich“), darunter Details mit Freigaben, Verlauf und Chat.
- Neue Einträge anderer Parteien erscheinen automatisch (alle 5 Sekunden).

## Revit (pyRevit-Reiter „DBK“)

Die Erweiterung liegt in `pyrevit/DBK.extension`; der Ordner `pyrevit` ist in pyRevit als Suchpfad eingetragen.

Zwei Knöpfe:

- **Durchbruchsprüfung** – andockbare Leiste wie Eigenschaften/Projektbrowser: Suche, Filter („Für mich“,
  Status, Stand), Liste, Detail mit Maßen und Freigaben, **Freigeben/Ablehnen/weitere Status**, Verlauf und
  Nachrichten. „In 3D zeigen“, „Im Grundriss“, „Nur markieren“ finden den Durchbruch im eigenen Modell oder in
  der Verknüpfung (z. B. TGA-Modell im Architekturmodell). Schreibt dieselben Ereignisse wie der Viewer.
  Die Leiste wird beim Start von Revit angemeldet – nach Installation/Update Revit einmal neu starten.
- **Durchbruchskoordination** – das Fenster bleibt neben Revit offen. Reiter in der Reihenfolge des Ablaufs:

| Reiter | Was passiert |
|---|---|
| **Projekt** | Projektordner wählen – damit ist das Projekt bestimmt (legt bei Bedarf ein neues an). Dazu Name, Firma, Rolle, Modellkürzel. Einmal je Revit-Modell – die Zuordnung steht danach im Modell, jedes Fenster zeigt das Projekt an. Geschosse ermittelt das Werkzeug aus den Ebenen |
| **Ansichten** | Was im Viewer zu sehen ist. **3D**: je Zeile eine 3D-Ansicht, Name im Viewer, Format (FBX schnell / IFC mit Eigenschaften), Verknüpfungen (*Modell + Verknüpfungen einzeln*, *Alles in einem Modell*, *Nur dieses Modell*). **2D**: Grundrisse und Schnitte mit allen Beschriftungen als Bild – im Viewer passgenau über dem Modell. Unveränderte Ansichten werden übersprungen |
| **Durchbrüche** (TGA, ELT, Labor) | Links: welche Familien/Typen Durchbrüche sind. Rechts: ein **Stand** = Name + **3D-Ansicht** (z. B. „EG Rohbau“). Was von diesen Familien in der Ansicht sichtbar ist, gehört dazu – je Durchbruch markiert als neu, geändert, unverändert, entfällt. „Ansicht anlegen“ erzeugt „DBK Stand – Name“ |
| **Einreichen** | Den ganzen Stand als Momentaufnahme einreichen: Neues und Geändertes geht in die Prüfung, Unverändertes bleibt mit seinen Entscheidungen, was fehlt, fällt heraus. „Stand zurückziehen“ entfernt ihn für alle. Im Viewer lässt sich jeder Stand einzeln ein-/ausblenden und (von der eigenen Firma) zurückziehen |

Oben: **Nächster Hinweis**, **In Revit zeigen**, **Viewer öffnen**. Prüfen, Kommentieren und Freigeben passieren im Viewer oder in der Leiste **Durchbruchsprüfung**.

Grundsatz: Was in der Exportansicht sichtbar ist, geht raus. Die Durchbruch-Familien werden standardmäßig
weggelassen (abschaltbar) – sie kommen als Stände mit Prüfstatus über „Einreichen“.

## Tests

```powershell
cd tests; py -m unittest -v
```

Die Tests laufen unter CPython 3 und unter IronPython 2.7 in Revit (pyRevit).
Abgleich Python ↔ JavaScript: Entwicklungs-Server starten und <http://127.0.0.1:8765/test/> öffnen.

## Stand

- [x] Kern (Python), Datenformat, Tests
- [x] Web-App: Modelle laden, Durchbrüche nach Status, 3D/Grundriss, Geschosse, Schnitte, Freigeben/Ablehnen, Chat
- [x] Web-App: Seitenleiste Modelle/Stände, Modell ausrichten, IFC/FBX im Browser hochladen
- [x] pyRevit: Durchbruchskoordination (Projekt, Ansichten 3D/2D, Durchbrüche, Stände, Einreichen)
- [x] Plan-Ebene: Grundrisse/Schnitte aus Revit als Bild mit Lage
- [ ] pyRevit: Parameter-Sync (Status zurück nach Revit)
- [ ] Verwaltungs-Seite (Rollen, Status, Pflicht-Matrix)
- [ ] Berichte (PDF-Verlauf, BCF)
