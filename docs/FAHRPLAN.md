# Fahrplan

Stand der Abstimmung: Was als Nächstes gebaut wird, in dieser Reihenfolge. Jede Phase ist für
sich nutzbar; spätere Phasen bauen auf den früheren auf.

Zwei Wege bleiben die Grundidee:

1. **Durchbrüche einreichen** (Revit) – je Stand eine 3D-Ansicht.
2. **Ansichten** (Revit) – 3D-Ansichten als Modelle (FBX/IFC, je Verknüpfung einzeln) und 2D-Grundrisse/Schnitte als Pläne.

Geprüft wird im **Viewer** oder – gleichwertig – in der **Revit-Prüfleiste**. Beide schreiben
dieselben Ereignisse in denselben Projektordner.

---

## Phase 1 – Richtige Daten ✓ (gebaut)

### 1.1 Projektbezug eindeutig

Problem heute: Projektordner und Modellkürzel sind *eine* Einstellung je Rechner. Wer mehrere
Projekte bearbeitet, reicht ins falsche Projekt ein, und das Modellkürzel passt nicht zum Modell.

- `projekt.json` bekommt eine feste **Projekt-ID** (wird beim Anlegen erzeugt) neben dem Namen.
- Die Zuordnung **Revit-Modell → Projektordner + Modellkürzel** wird **im Revit-Modell selbst**
  gespeichert (Extensible Storage). Wer das Modell öffnet, landet automatisch im richtigen Projekt;
  das gilt auch für Kollegen am selben Modell.
- Persönlich (je Rechner) bleiben nur Name, Firma, Rolle.
- Jedes Fenster zeigt oben groß **„Projekt: <Name>“**. Passt die Projekt-ID im Ordner nicht zur
  gespeicherten, gibt es eine deutliche Warnung statt stillem Weiterarbeiten.
- Die Architektur verbindet ihr eigenes Modell einmal mit demselben (synchronisierten)
  SharePoint-Ordner – danach ist für alle sichtbar, dass es dasselbe Projekt ist.
- Der Viewer zeigt Projektname und, je Modell und Durchbruch, aus welchem Revit-Modell er stammt.

### 1.2 Abmessungen und Lage der Durchbrüche

Problem heute: Maße kommen aus der Begrenzungsbox. Die Durchbruchfamilien enthalten
Symbollinien zwischen den Ebenen – die Box ist dadurch mehrere Meter hoch, und die Parameter
„Breite/Höhe“ sind das Rohr, nicht die Öffnung.

- **Geometrie** aus den Volumenkörpern der Familie (ohne Linien/Symbole) statt aus der Box.
- **Maße** aus den Parametern der Öffnung, über eine Zuordnung im Prüfset:
  - Vorgabe-Erkennung: `Gesamt Breite`, `Gesamt Höhe`, `Gesamt Länge`, `Gesamt Tiefe`,
    sonst `Breite`/`Höhe`/`Länge`/`Tiefe`, sonst Volumenkörper.
  - Wand: **B × H**, Tiefe = Wanddicke. Decke: **B × L**, Tiefe = Deckendicke. Rund: **Ø**.
  - Lage: UK/OK bezogen auf die Ebene (OKFF) und absolut.
- In der Liste sichtbar, welcher Parameter genommen wurde (zum Gegenprüfen).
- Folge: Beim ersten Einreichen danach gelten alle Durchbrüche einmal als „geändert“.

---

## Phase 2 – Einreichen = Stand als Momentaufnahme ✓ (gebaut)

### 2.1 Stand = 3D-Ansicht

- Ein **Stand** ist nur noch: Name + 3D-Ansicht. Was in der Ansicht von den Familien
  „in der Koordination“ sichtbar ist, gehört zum Stand. Ebenen-Filter, Auswahlvorlagen und
  Häkchen je Exemplar entfallen.
- „Ansicht anlegen“ bleibt als Hilfe (neue 3D-Ansicht mit allen Durchbrüchen, dann in Revit
  ausblenden, was nicht dazugehört).

### 2.2 Einreichen

- **Alles Sichtbare** des Stands wird eingereicht, je Durchbruch markiert als
  **neu**, **geändert** (Lage/Größe) oder **unverändert**.
- Was vorher im Stand war und jetzt fehlt, **fliegt raus** – ohne „gelöscht“-Anzeige für die
  Prüfer.
- Solange noch niemand geprüft hat, darf beliebig oft neu eingereicht werden.
- Nach einer Prüfung: unverändert bleibt die Entscheidung bestehen; geändert setzt die
  Prüfung dieses Durchbruchs zurück.
- **Ein Ereignis je Einreichung** statt je Durchbruch (heute ~2.000 Einzeldateien → der
  Viewer braucht 30 s zum Öffnen). Neues Ereignis `stand_eingereicht`
  `{stand, runde, objekte: [...]}`; alte Einzelereignisse bleiben lesbar.

### 2.3 Stand zurückziehen

- `stand_zurueckgezogen {stand}` – nur die einreichende Firma, im Viewer (Stand-Menü) und in Revit.
- Alle Durchbrüche des Stands verschwinden für alle.

---

## Phase 3 – Viewer: Durchbrüche klar sehen ✓ (gebaut, offen: Schnitte für alle)

- ✓ **Darstellung**: Durchbrüche farbig nach Status; Beschriftung automatisch nur für Auswahl, Maus darüber
  und Nahsicht, ohne Überdeckung. **Röntgen**: Modelle blass, Durchbrüche immer sichtbar.
- ✓ **Hinspringen**: Klick in Liste/Modell → Schnittbox 2 m um den Durchbruch.
- ✓ **2D-Grundriss** je Geschoss (Schnitt 1,00 m über OKFF), Durchbrüche als Umriss mit Status.
- ✓ **Plan-Ebene**: beschriftete Grundrisse/Schnitte aus Revit (Reiter „Ansichten“) passgenau über dem Modell.
- ✓ **Schnitte und Schnittboxen**: benannt, Werkzeug unten links, umschalten oben. Offen: „für alle speichern“.
- ✓ **Messen** und **Ausrichten mit Punktpaaren**.
- ✓ **Große Modelle**: FBX zusammengelegt und einmal kompakt abgelegt (`.dbkg`, etwa ein Zehntel der Größe,
  Laden in Sekunden).
- ✓ Seitenleiste: Stände mit Zurückziehen und Status-Chips.

---
## Phase 4 – Revit-Prüfleiste ✓ (gebaut)

- Neuer Knopf **„Durchbruchsprüfung“**: andockbare Leiste wie Eigenschaften/Projektbrowser.
- Gleicher Inhalt wie rechts im Viewer: Suche, Filter, Liste, Detail mit Status-Knöpfen und
  Verlauf/Chat.
- Klick auf einen Durchbruch markiert ihn in Revit und zoomt hin – auch in der verknüpften
  TGA-Datei (Architektur prüft im eigenen Modell). Optional Schnittbox um den Durchbruch.
- Schreibt dieselben Ereignisse; Änderungen aus dem Viewer erscheinen nach dem Abgleich
  (OneDrive/SharePoint) von selbst.

---

## Phase 5 – Zusammenarbeit über SharePoint

- Anleitung: SharePoint-Bibliothek synchronisieren, Pfad als Projektordner wählen,
  Gastzugriff für externe Firmen.
- Anzeige „zuletzt abgeglichen“ und Hinweis, wenn Dateien noch nicht synchronisiert sind.

---

## Offen / später

- BCF- und PDF-Bericht (nutzt die Plan-Ebene).
- Anzeige eines frei wählbaren Revit-Parameters als Beschriftung im Viewer.
