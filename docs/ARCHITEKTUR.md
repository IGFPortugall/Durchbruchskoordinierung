# Architekturkonzept Durchbruchskoordinierung

Stand: 24.11.2026 – Entwurf 2 (dezentral, ohne Server)

## 1. Ziel

Bauteile – zuerst Durchbrüche, später beliebige andere – werden von allen Beteiligten
geprüft, freigegeben oder abgelehnt, mit lückenlosem Verlauf.

Rollen sind **je Projekt frei definierbar** (Verwaltungs-Seite), typisch:
**TGA (HLS)**, **ELT**, **Labor**, **Architektur**, **Tragwerk**, **Brandschutz**, **Bauherr**.

Grundsätze:

- **Open Source, kein zentraler Server.** Jede Partei besitzt ihre eigenen Daten.
- **Austausch über einen gemeinsamen Ordner** (OneDrive / SharePoint / ACC Docs / Netzlaufwerk).
- **Jede Partei schreibt nur ihre eigenen Dateien.** Dadurch entstehen keine Sync-Konflikte.
- **Revit-Nutzer arbeiten in Revit** (pyRevit) und behalten alle Revit-Funktionen.
- **Alle anderen arbeiten im Browser** (That Open Components, läuft lokal, ohne Server).
- **BCF und PDF sind Berichte**, kein Arbeitsformat.
- **Vorerst keine Anmeldung**: Name, Firma und Rolle werden im ersten Dialog gewählt.
- **Ohne Anleitung bedienbar**: wenig Text in der Oberfläche, Erklärungen nur als Tooltip (Mouse-Over).

### Ablauf im Team

| Schritt | Wer | Wo | Was |
|---|---|---|---|
| 1. Setzen | TGA, ELT, Labor (Ersteller) | eigene Software (Revit, andere) | Durchbrüche modellieren |
| 2. Prüfrunde starten | Ersteller | Revit-Prüfset bzw. Web (IFC hochladen) | im Baum Kategorie → Familie → Typ auswählen, Runde benennen, Frist setzen, einreichen |
| 3. Prüfen | Architektur, Tragwerk, Bauherr … (Prüfer) | Revit **oder** Browser | ansehen, im Chat kommentieren, **freigeben** oder **ablehnen** |
| 4a. Nacharbeiten | Ersteller | eigene Software | Durchbruch verschieben/anpassen → erneut einreichen |
| 4b. Bleibt so | Prüfer + Ersteller | Chat | Lösung auf Seite Architektur/Statik → erneut einreichen, Prüfer ändert Entscheidung |
| 5. Abschließen | Projektleitung | Verwaltung | Stichtag setzen → PDF-Bericht, freigegebene Durchbrüche gelten als abgeschlossen |

Revit und Browser schreiben in dieselben Dateien – eine Freigabe in Revit erscheint im Browser und umgekehrt.

**Status**: Standard sind *freigegeben* und *abgelehnt* je Prüfer-Rolle. Weitere Status
(z. B. „zurückgestellt“, „unter Vorbehalt“) lassen sich je Projekt in der Verwaltung ergänzen,
jeweils mit Farbe und Wirkung (blockiert / blockiert nicht).

**Prüfrunde**: Name, Frist, Ersteller, Liste der eingereichten Bauteile. Ein Bauteil kann in
mehreren Runden vorkommen; der Verlauf zeigt, in welcher Runde was passiert ist.

**Kommentare als Chat**: je Durchbruch ein Verlauf mit Nachrichten und Status-Ereignissen,
jeweils mit Name, Rolle, Firma und Zeitpunkt – so ist nachvollziehbar, wer wann was getan hat.

**Live-Übertragung**: Revit (.NET `FileSystemWatcher`) und Web-App (Ordner alle paar Sekunden prüfen)
zeigen neue Ereignisse automatisch an. Die Verzögerung hängt am Sync-Dienst
(OneDrive meist Sekunden, ACC Desktop Connector eher Minuten). Reicht das nicht, kann später
ein kleiner, selbst betriebener Benachrichtigungs-Dienst ergänzt werden, der nur „neue Datei da“
meldet – die Daten bleiben trotzdem in den Dateien der Parteien.

**PDF-Bericht je Stichtag**: eine Seite pro Durchbruch mit Kopf (Nummer, Status, Wirtsbauteil,
Größe, Lage), Grundriss-Ausschnitt mit Markierung, kleinem 3D-Schnitt, Freigabe-Tabelle der
Rollen und kompaktem Verlauf. Davor eine Übersichtsseite mit Kennzahlen.
Bilder werden beim Einreichen bzw. Freigeben aus Revit oder dem Web-Viewer erzeugt und mitgespeichert.

## 2. Austauschprinzip: Ereignisse statt Datenbank

Statt einer gemeinsamen Datenbank legt jede Partei **Ereignisse** als kleine JSON-Dateien
im gemeinsamen Ordner ab. Jeder Client liest alle Ereignisse und berechnet daraus den
aktuellen Stand. Ereignisse werden nie geändert, nur ergänzt.

```
<Projektordner>/Durchbruchskoordinierung/
├── projekt.json                   Projektname, Rollen, Prüfregeln
├── pruefsets/
│   └── IGF.json                   welche Kategorien/Familien/Typen geprüft werden
└── ereignisse/
    ├── IGF/                       nur IGF schreibt hier
    │   └── 20261124T102011123Z_000017_9f0c1a2b.json
    ├── Architekt_XY/
    └── Tragwerk_Z/
```

Der Bauteil-Stand (Lage, Größe, Parameter) steckt im Ereignis `eingereicht` bzw. `geaendert`;
ein eigener Ordner für Objekte ist nicht nötig. Details: [DATENFORMAT.md](DATENFORMAT.md).

Warum **eine Datei pro Ereignis**: OneDrive & Co. synchronisieren neue Dateien zuverlässig,
gleichzeitiges Bearbeiten derselben Datei durch zwei Parteien führt dagegen zu Konfliktkopien.
Eine SQLite-Datei im geteilten Ordner wäre aus demselben Grund ungeeignet.

Lokal hält jeder Client einen **Zwischenspeicher** (SQLite im Benutzerprofil),
damit Filtern und Suchen in Revit und im Browser schnell bleibt.

## 3. Prüfobjekte (allgemein, nicht nur Durchbrüche)

Jede Firma definiert ein **Prüfset**: im Tool wird in einer Baumstruktur
**Revit-Kategorie → Familie → Typ** angehakt, welche Bauteile zur Prüfung veröffentlicht werden.
So kann jede Firma ihre eigenen Familien nutzen, und später lassen sich auch andere Dinge
freigeben (z. B. Schächte, Bodeneinläufe, Fundamente für Geräte).

**Prüfobjekt** (Stand, wie es veröffentlicht wurde)
- `revit_unique_id`, `ifc_guid` (aus der UniqueId abgeleitet → Abgleich im IFC-Viewer)
- Quellmodell, veröffentlichende Firma, Kategorie, Familie, Typ
- Nummer (lesbar), Ebene, Lage (Bounding Box, Einfügepunkt), ausgewählte Parameter
- Wirtsbauteil (falls ermittelbar), durchdringende Gewerke
- `geometrie_hash` – erkennt Änderungen an Größe und Lage

**Ereignis**
- `id`, Zeitpunkt, Firma, Name, Rolle
- Art: `pruefrunde_gestartet | eingereicht | geaendert | geloescht | status | nachricht`
  (`status` trägt den Wert, z. B. `freigegeben`, `abgelehnt` oder einen projektspezifischen Status)
- Bezug: Prüfobjekt + `geometrie_hash`, für den die Aussage gilt
- Kommentar, optional Bild

### Status-Logik

- Rollen und Pflicht-Regeln werden **je Projekt auf der Verwaltungs-Seite** gepflegt und in
  `projekt.json` gespeichert (Regel je Kategorie / Wirtsbauteil, z. B. tragende Wand →
  Tragwerk + Architektur). Nicht-Pflichtrollen dürfen kommentieren, blockieren aber nicht.
- **Gesamtstatus**: `abgelehnt`, sobald eine Pflichtrolle ablehnt; `freigegeben`, wenn alle
  Pflichtrollen freigegeben haben; sonst `in Prüfung`.
- Nur die **letzte** Aussage einer Rolle zum **aktuellen** `geometrie_hash` zählt.
  Ändert sich die Geometrie, gelten alte Freigaben automatisch nicht mehr.

## 4. Revit (pyRevit-Extension)

pyRevit 7, IronPython 2.7, WPF-Fenster über `pyrevit.forms`. Getestet mit Revit 2026.

- **Start-Dialog**: Name, Firma, Rolle, Projektordner wählen (wird lokal gemerkt).
- **Prüfset einrichten**: Baum Kategorie → Familie → Typ mit Häkchen.
- **Veröffentlichen**: Bauteile des Prüfsets einlesen, neue/geänderte/gelöschte erkennen, Dateien schreiben.
- **Prüf-Manager** (nicht-modales Fenster):
  - Liste aller Prüfobjekte (eigene und aus Links), Filter nach Status, Rolle, Ebene,
    Kategorie, Familie, Firma; Suche nach Nummer.
  - *Anzeigen 2D*: Grundriss/Schnitt öffnen, Ausschnitt auf das Bauteil zuschneiden.
  - *Anzeigen 3D*: 3D-Ansicht mit Schnittbox, verknüpfte Modelle sichtbar.
  - Auswählen / Isolieren in der aktiven Ansicht.
  - *Freigeben / Ablehnen / Kommentar* (auch für mehrere Bauteile auf einmal).
- **Parameter-Sync**: Status, Nummer, letzte Kommentare in Revit-Parameter schreiben.
  Damit funktionieren Ansichtsfilter, Farben, Bauteillisten und Beschriftungen ganz normal.

## 5. Web-App (für alle ohne Revit)

- Statische Web-Seite mit `@thatopen/components` + `@thatopen/ui` (MIT), läuft ohne Server.
- Liest den gemeinsamen Ordner direkt (File System Access API, Chrome/Edge) und schreibt
  eigene Ereignisse in den eigenen Unterordner.
- IFC-Modelle aller Gewerke laden; Prüfobjekte über `ifc_guid` finden und nach Status einfärben.
  Fehlt ein Bauteil im IFC, wird es aus der Bounding Box als Körper gezeichnet.
- Liste und Filter wie in Revit, Klick → Kamera fliegt hin, Schnittebene optional.
- Abstimmung mit Antonio / That Open Company.

### Inhalt des Viewers

Bewusst schlank – nur, was zum Prüfen nötig ist:

| Ebene | Quelle | Hinweis |
|---|---|---|
| Architektur | IFC der Architektur im Projektordner (`modelle/ARC/`) | beim ersten Öffnen in Fragments umgewandelt und lokal zwischengespeichert |
| Tragwerk | IFC der Tragwerksplanung (`modelle/TWP/`) | wie oben |
| Durchbrüche | aus den Ereignissen (Bounding Box, Form, Status) | kein TGA-Modell nötig; Farbe = Status |
| Beschriftung | aus den Ereignissen | Nummer und Größe als Label am Durchbruch, immer aktuell |
| Plan je Geschoss | beschriftete Ansicht (Revit-Export oder PDF) | maßstäblich auf Geschosshöhe eingepasst |
| Achsraster | `IfcGrid` aus dem IFC | optional |

### Modelle als Fragments – einmal erzeugt, alle sehen dieselbe Version

Fragments ist das schnelle Ladeformat von That Open. Ziel: Jedes Modell wird **einmal**
umgewandelt und als Datei in den Projektordner gelegt; alle laden genau diese Datei.

```
modelle/
  ARC/
    3f9a1c7e2b4d6a80.frag     Dateiname = Hash des Quell-IFC → jede Version eindeutig
    3f9a1c7e2b4d6a80.json     Geschosse, Pläne, Stand
  TWP/ …
```

**Veröffentlichen aus Revit** (Werkzeug Durchbruchskoordination, Reiter „Ansichten“):
1. Je Zeile eine 3D-Ansicht; Durchbrüche und – je nach Einstellung – Verknüpfungen bzw. das eigene
   Modell werden in einer zurückgerollten Transaktion ausgeblendet.
2. Export als **FBX** (schnell, Revit-eigen; dazu `<Hash>.json` mit Kategorie/Familie/Typ/Ebene/System
   je Bauteil und Bounding Box in mm – daraus richtet der Viewer das FBX aus) oder als **IFC**
   (langsam, mit Psets; der Browser wandelt beim ersten Öffnen in Fragments um und legt die `.frag` ab).
3. Dateien in `modelle/<Modell>/` ablegen und Ereignis `modell_veroeffentlicht` schreiben.
4. Die Liste der Exporte steht im Prüfset der Firma unter `viewer_exporte`; unveränderte Modelle
   (gleiche Revit-Dokumentversion, auch der Verknüpfungen) werden übersprungen.

**2D-Pläne** (gleicher Reiter): Grundrisse und Schnitte werden in einer zurückgerollten Transaktion
zugeschnitten (Zuschnitt aktiv, Rahmen unsichtbar, Beschriftungszuschnitt eng) und als PNG exportiert.
Das Ereignis `modell_veroeffentlicht` (Format `png`) trägt unter `plan` die vier Ecken in Revit-
Koordinaten; der Viewer legt das Bild dort hin (Grundriss: knapp über der Ebene, im Grundriss-Modus
wie ein Blatt über dem Modell und unter den Durchbrüchen; Schnitt: senkrecht in der Schnittebene).

**Ohne Revit**: IFC oder FBX im Browser hochladen (Feld „+ Modell laden“) → liegt danach genauso im Ordner.

**Ausrichtung**: Passt ein Modell nicht zu den anderen, wird es im Viewer verschoben/gedreht.
Jeder kann das lokal (nur im eigenen Browser); der Besitzer des Modells kann die Lage mit
`modell_ausrichtung` für alle festschreiben.

**Versionen**:
- Welche Version aktuell ist, steht im Ereignis `modell_veroeffentlicht` – nicht im Dateinamen.
  Dadurch sehen alle denselben Stand, sobald der Ordner synchronisiert ist.
- Nur die Firma, die ein Modell zuerst veröffentlicht hat, kann neue Versionen veröffentlichen.
- Alte Versionen bleiben liegen; der Viewer zeigt sie auf Wunsch („Stand 03.12.“).
- Jede Freigabe speichert mit, gegen welche Modellversionen geprüft wurde
  (`kontext` im Status-Ereignis) – im PDF-Bericht nachvollziehbar.
- Der Browser speichert geladene Fragments zusätzlich lokal; bei gleichem Hash wird nichts neu geladen.

### Fließender Wechsel 3D ↔ Grundriss

- **Eine Szene, eine Kamera.** Der Wechsel ist nur eine Kamerafahrt (ca. 0,7 s) um denselben
  Zielpunkt – Auswahl, Zoom und Position bleiben erhalten.
- 3D → Grundriss: Kamera schwenkt senkrecht nach unten, Norden oben, Schnittebene fährt auf
  1,00 m über OKFF; Plan-Ebene blendet ein.
- Grundriss → 3D: zurück auf den zuletzt genutzten Blickwinkel, Schnittebene auf Oberkante Geschoss.
- Geschoss wechseln: Zielpunkt fährt nur senkrecht, darüberliegende Geschosse werden weggeschnitten.
- Im Grundriss verschiebt Ziehen die Ansicht, im 3D dreht es.
- Ausgewählter Durchbruch bleibt markiert und wird bei Auswahl in die Bildmitte gefahren.

### Geschoss-Ansicht

- Geschossliste aus `IfcBuildingStorey` (bzw. Ebenen) mit Anzahl offener Durchbrüche je Geschoss.
- Modi: **3D** (frei drehen), **Grundriss** (Draufsicht, Schnittebene z. B. 1,00 m über OKFF,
  Drehen gesperrt, auf Wunsch freigeben), **Schnitt** (Schnittbox um den gewählten Durchbruch).
- Im Grundriss wird darüber Liegendes ausgeblendet; die Decke darunter bleibt sichtbar, damit
  Deckendurchbrüche erkennbar sind.

### Beschriftete Ansichten (Plan-Ebene)

Die Beschriftung der Pläne (Raumstempel, Bemaßung, Achsen, **Beschriftungen der Durchbrüche**)
steckt nicht im IFC. Sie kommt als **Plan-Ebene** direkt aus den Revit-Ansichten bzw. als PDF:

- **Aus Revit** (pyRevit, Button „Pläne veröffentlichen“): gewählte Grundriss-/Schnittansichten
  werden mit dem Revit-eigenen PDF-Export als **Vektor-PDF** ausgegeben – genau so, wie sie in
  Revit aussehen, inkl. aller Beschrifter und Ansichtsfilter.
  - Da Status, Nummer und Kommentar per Parameter-Sync in Revit stehen, zeigen die
    Durchbruchs-Beschrifter im PDF automatisch den aktuellen Stand (z. B. `TGA-0042 · 400×300 · UK +2,10 · abgelehnt`),
    und Ansichtsfilter färben nach Status.
  - Mitgespeichert wird die Lage des Zuschnittbereichs in Projektkoordinaten und der Maßstab →
    der Plan liegt automatisch richtig über dem Modell. Zur Sicherheit wird die Passung an zwei
    Achsschnittpunkten geprüft; passt sie nicht, wird wie bei PDFs von Hand eingepasst.
- **Ohne Revit**: PDF-Plan hochladen und mit zwei Punkten (z. B. Achsschnittpunkten) einpassen.
- Anzeige im Browser mit `pdf.js` (Vektor, bleibt beim Zoomen scharf) – keine Umwandlung nötig.
- Abgelegt unter `plaene/<Firma>/<Geschoss>_<Name>_<Hash>.pdf` + `.json` (Lage, Maßstab, Geschoss, Stand).

Drei Arten, den Plan zu sehen – alle mit fließendem Wechsel, Auswahl bleibt erhalten:

| Modus | Was man sieht |
|---|---|
| **3D** | Modelle + Durchbrüche, frei drehbar |
| **Grundriss** | Modell von oben geschnitten, Plan-Ebene halbtransparent darübergelegt |
| **Plan** | nur das PDF, flach wie im PDF-Viewer – aber Durchbrüche sind anklickbar (Lage bekannt) und mit Status-Rahmen markiert |

- Der Plan zeigt den Stand seines Exports; Datum steht sichtbar am Plan. Ist ein Durchbruch
  seit dem Export geändert worden, wird seine Markierung als „Plan veraltet“ gekennzeichnet.
- Der **PDF-Bericht** nutzt dieselben Revit-Pläne: der Grundriss-Ausschnitt je Durchbruch wird
  aus dem Plan-PDF ausgeschnitten – mit den originalen Beschriftern statt einer nachgebauten Grafik.

## 6. Berichte

- **BCF** (2.1, optional 3.0) über IfcOpenShell `bcf`: ein Topic je Prüfobjekt, Viewpoint mit
  Kamera und Komponente (`ifc_guid`), Kommentare aus dem Verlauf.
- **PDF-Verlaufsbericht**: je Prüfobjekt Stammdaten, Bild, Freigabe-Matrix der Rollen,
  chronologischer Verlauf; filterbar nach Ebene, Status, Zeitraum.

Beides wird lokal erzeugt (Python, CPython-Skript bzw. aus der Web-App).

## 7. UI-Konzept

Gleiche Begriffe, Farben und Abläufe in Revit und Web, damit jede Partei sich in beiden zurechtfindet.

**Farben (überall gleich)**: gelb = in Prüfung / geändert, rot = abgelehnt, grün = freigegeben, grau = nicht relevant.

**Revit**
1. *Start-Dialog* – Projektordner, Name, Firma, Rolle (Rollen aus der Verwaltung). Wird gemerkt.
2. *Prüfset* – Baum Kategorie → Familie → Typ mit Häkchen und Anzahl; „Veröffentlichen“.
3. *Prüf-Manager* – andockbares Fenster (pyRevit `DockablePane`), bleibt beim Arbeiten offen:
   - Kopf: angemeldete Rolle, Stand der Daten, Aktualisieren.
   - Filterleiste: Suche, Status, Ebene, Wirtsbauteil, Schalter **„Wartet auf mich“** (Standard an).
   - Kennzahlen: in Prüfung, wartet auf mich, abgelehnt, freigegeben.
   - Liste: Nummer, Wirt + Größe, erfüllte Pflichtrollen (z. B. 3/4), Status. Mehrfachauswahl.
   - Detail: Buttons **2D / 3D / Isolieren**, Freigabe-Matrix der Rollen, letzter Kommentar,
     Kommentarfeld, **Freigeben / Ablehnen** (gilt für alle ausgewählten Zeilen).
   - Auswahl in Revit ↔ Auswahl in der Liste sind gekoppelt.

**Web-App**
4. Dreiteilig: links Modelle + Liste, Mitte 3D-Viewer (Schnitt, Messen, Legende), rechts Detail
   mit „Ihre Aufgabe“, Kommentar, Freigeben / Ablehnen, Bild anhängen.

**Verwaltung** (Teil der Web-App, je Projekt)
5. Rollen und Firmen pflegen; **Pflicht-Matrix** Wirtsbauteil × Rolle mit den Werten
   *Pflicht / Info / –*; Zusatzregeln (z. B. Größe > 1 m² → Bauherr Pflicht); Berichte exportieren.
   Speichert in `projekt.json`.

## 8. Vorgehen

1. **Kern (Python, ohne Revit)**: Dateiformate (JSON-Schema), Einlesen der Ereignisse,
   Status-Berechnung, lokaler Zwischenspeicher. Mit Tests.
2. **Revit MVP**: Start-Dialog, Prüfset-Baum, Veröffentlichen, Prüf-Manager mit Filtern,
   2D/3D anzeigen, Freigeben/Ablehnen, Parameter-Sync.
3. **Berichte**: PDF-Verlauf, BCF-Export.
4. **Web-App** mit That Open Components.
5. Pilot in einem laufenden Projekt (Projektdaten bleiben im Projektordner, nie im Repository).

Entwicklung zunächst lokal mit einem Testordner.

## 9. Festlegungen

- **Zeitreihenfolge**: UTC-Zeitstempel + fortlaufende Nummer je Firma; bei Widerspruch gilt „abgelehnt schlägt freigegeben“.
- **Nummern** mit Firmenkürzel (z. B. `TGA-2_OG01-0042`), damit ohne zentrale Stelle keine Dubletten entstehen.
- **Löschen**: gelöscht ist gelöscht. Das Bauteil verschwindet aus Listen, Viewer und Berichten
  (das Ereignis `geloescht` existiert nur technisch, damit alle Clients es entfernen).
- **Geometrie-Hash** auf 5 mm gerundet, in Projektkoordinaten.
- **IFC-GUID** aus dem Revit-Parameter `IfcGUID`; beim IFC-Export „IFC-GUID speichern“ aktivieren.
- **Archivierung**: jede Firma fasst ihre alten Ereignisse regelmäßig zu einer Archivdatei zusammen.
- **Keine Anmeldung** im Pilot; später optional Signatur je Firma.
