# -*- coding: utf-8 -*-
"""Modelle zum Viewer – 3D-Ansichten als FBX/IFC in den Projektordner stellen.

Eine Zeile je Export: welche 3D-Ansicht, unter welchem Namen im Viewer, was mit
Verknüpfungen passiert (mit exportieren / weglassen / jede einzeln als eigenes Modell)
und welches Format. Durchbrüche sind nie Teil des Modells – die kommen über „Einreichen“.

Gespeichert wird die Liste im Prüfset der eigenen Firma unter ``viewer_exporte``.
"""
from __future__ import unicode_literals

import json
import os
import shutil
import tempfile
import time
import traceback
import uuid

from System.Windows import Thickness, GridLength, GridUnitType, VerticalAlignment, Visibility
from System.Windows.Controls import (Border, Button, CheckBox, ColumnDefinition, ComboBox, Grid, TextBlock,
                                     TextBox)
from System.Windows.Input import Cursors
from System.Windows.Media import SolidColorBrush, ColorConverter
from Autodesk.Revit import DB, UI
from pyrevit import forms

from . import aktionen, einstellungen, sammeln, viewer_start
from .fortschritt import Abgebrochen, Fortschritt
from .sammeln import eid

XAML = os.path.join(os.path.dirname(__file__), "ui", "modelle.xaml")

ALLES, EIGEN, JE_LINK = "alles", "eigen", "links"
INHALT = [(ALLES, "Alles wie in der Ansicht"), (EIGEN, "Nur dieses Modell"), (JE_LINK, "Je Verknüpfung einzeln")]
INHALT_HILFE = {
    ALLES: "Ein Modell im Viewer – mit allen Verknüpfungen, die in der Ansicht sichtbar sind.",
    EIGEN: "Nur Elemente dieses Revit-Modells, Verknüpfungen werden für den Export ausgeblendet.",
    JE_LINK: "Jede sichtbare Verknüpfung wird ein eigenes Modell im Viewer (einzeln ein-/ausblendbar). "
             "Das eigene Modell bleibt dabei weg.",
}
FORMATE = [aktionen.FBX, aktionen.IFC]


def _pinsel(farbe):
    b = SolidColorBrush(ColorConverter.ConvertFromString(farbe))
    b.Freeze()
    return b


ROT, GRAU, LINIE = _pinsel("#be0a26"), _pinsel("#71717a"), _pinsel("#e4e4e7")


# ------------------------------------------------------------------ Logik ohne Fenster

def laden(einst):
    return sammeln.pruefset_laden(einst["projektordner"], einst["firma"]).get("viewer_exporte", [])


def speichern(einst, exporte):
    ps = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
    ps["viewer_exporte"] = exporte
    sammeln.pruefset_speichern(einst["projektordner"], einst["firma"], ps)


def neu(ansicht, name):
    return {"id": uuid.uuid4().hex[:8], "ansicht": ansicht, "name": name, "inhalt": EIGEN,
            "format": aktionen.FBX, "aktiv": True}


def ansichten_3d(doc):
    return dict((v.Name, v) for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D)
                if not v.IsTemplate and v.CanBePrinted)


def sichtbare_links(doc, ansicht):
    """RevitLinkInstances, die in der Ansicht sichtbar und geladen sind."""
    return [l for l in DB.FilteredElementCollector(doc, ansicht.Id).OfClass(DB.RevitLinkInstance)
            if l.GetLinkDocument() is not None]


def link_titel(link):
    t = link.GetLinkDocument().Title
    return t[:-4] if t.lower().endswith(".rvt") else t


def modell_kuerzel(einst, name):
    basis = einstellungen.kuerzel_bereinigen(einst.get("modellkuerzel") or einst["firma"])
    rest = einstellungen.kuerzel_bereinigen(name, 24)
    return "%s-%s" % (basis, rest) if rest else basis


def ziele(doc, einst, x, ansicht):
    """Was aus einer Zeile exportiert wird: Liste von dicts (kuerzel, name, verstecken, links)."""
    links = sichtbare_links(doc, ansicht)
    inhalt = x.get("inhalt") or EIGEN
    if inhalt == ALLES:
        return [{"kuerzel": modell_kuerzel(einst, x["name"]), "name": x["name"], "verstecken": [],
                 "eigen": True, "links": links}]
    if inhalt == EIGEN:
        return [{"kuerzel": modell_kuerzel(einst, x["name"]), "name": x["name"],
                 "verstecken": [l.Id for l in links], "eigen": True, "links": []}]
    host = None
    ergebnis = []
    for l in links:
        if host is None:
            host = [e.Id for e in DB.FilteredElementCollector(doc, ansicht.Id).WhereElementIsNotElementType()
                    if e.Category is not None and e.Category.CategoryType == DB.CategoryType.Model
                    and not isinstance(e, DB.RevitLinkInstance) and e.CanBeHidden(ansicht)]
        titel = link_titel(l)
        andere = [o.Id for o in links if o.Id != l.Id]
        ergebnis.append({"kuerzel": modell_kuerzel(einst, "%s %s" % (x["name"], titel)),
                         "name": "%s – %s" % (x["name"], titel), "verstecken": host + andere,
                         "eigen": False, "links": [l]})
    return ergebnis


def version_mit_links(doc, links):
    teile = [aktionen.modell_version(doc) or "?"]
    for l in links:
        teile.append(aktionen.modell_version(l.GetLinkDocument()) or "?")
    return "|".join(teile)


# ------------------------------------------------------------------ Fenster

class _Warteschlange(UI.IExternalEventHandler):
    def __init__(self, fenster):
        self.fenster = fenster
        self.auftraege = []

    def Execute(self, uiapp):
        while self.auftraege:
            titel, f = self.auftraege.pop(0)
            try:
                f(uiapp)
            except Abgebrochen:
                self.fenster.melden("„%s“ abgebrochen." % titel, fehler=True)
            except Exception as e:
                self.fenster.melden("Fehler bei „%s“: %s" % (titel, e), fehler=True)
                print(traceback.format_exc())
        self.fenster.beschaeftigt(False)

    def GetName(self):
        return "DBK Modelle zum Viewer"


class ModelleFenster(forms.WPFWindow):

    def __init__(self, doc):
        forms.WPFWindow.__init__(self, XAML)
        self.einst = einstellungen.laden()
        self._handler = _Warteschlange(self)
        self._ereignis = UI.ExternalEvent.Create(self._handler)
        alle = ansichten_3d(doc)
        self.ansichten = sorted(alle)
        self.links_je_ansicht = {}   # nur für Ansichten in der Liste (Lesen kostet bei vielen Ansichten Zeit)
        for x in (laden(self.einst) if einstellungen.vollstaendig(self.einst) else []):
            if x.get("ansicht") in alle:
                self.links_je_ansicht[x["ansicht"]] = [link_titel(l) for l in sichtbare_links(doc, alle[x["ansicht"]])]
        self.untertitel.Text = "%s  ·  %s" % (doc.Title, self.einst.get("firma") or "")
        self.m_neu.Click += lambda s, a: self._zeile_neu()
        self.m_los.Click += lambda s, a: self.exportieren()
        self.m_viewer.Click += lambda s, a: self._viewer()
        self.m_hilfe_fbx.Text = aktionen.FORMAT_TEXT[aktionen.FBX]
        self.m_hilfe_ifc.Text = aktionen.FORMAT_TEXT[aktionen.IFC]
        if not einstellungen.vollstaendig(self.einst):
            self.exporte = []
            self.m_los.IsEnabled = self.m_neu.IsEnabled = False
            self.melden("Bitte zuerst im Werkzeug „Durchbruchskoordination“ das Projekt einrichten.", fehler=True)
            self.zeichnen()
            return
        self.exporte = laden(self.einst)
        if not self.exporte:
            aktiv = doc.ActiveView
            start = aktiv.Name if isinstance(aktiv, DB.View3D) and aktiv.Name in self.ansichten else \
                (self.ansichten[0] if self.ansichten else None)
            if start:
                self.exporte = [neu(start, self.einst.get("modellkuerzel") or doc.Title)]
        self.zeichnen()
        self.melden("Je Zeile eine 3D-Ansicht. Unveränderte Modelle werden übersprungen.")

    # ---------------------------------------------------------------- Grundlagen

    def auftrag(self, titel, f):
        self._handler.auftraege.append((titel, f))
        self.beschaeftigt(True, titel)
        self._ereignis.Raise()

    def beschaeftigt(self, an, titel=None):
        self.busy.Visibility = Visibility.Visible if an else Visibility.Collapsed
        self.Cursor = Cursors.Wait if an else None
        if an and titel:
            self.melden("%s …" % titel)

    def melden(self, text, fehler=False):
        self.status.Text = text
        self.status.Foreground = ROT if fehler else GRAU

    def _sichern(self):
        if einstellungen.vollstaendig(self.einst):
            speichern(self.einst, self.exporte)

    # ---------------------------------------------------------------- Liste

    def zeichnen(self):
        self.zeilen.Children.Clear()
        if not self.exporte:
            t = TextBlock()
            t.Text = "Noch keine Ansicht – mit „+ Ansicht hinzufügen“ eine 3D-Ansicht wählen."
            t.Foreground = GRAU
            t.Margin = Thickness(4, 12, 4, 12)
            self.zeilen.Children.Add(t)
        for x in self.exporte:
            self.zeilen.Children.Add(self._zeile(x))

    def _spalten(self, g):
        for breite in (30, 2.2, 1.8, 1.8, 0.9, 1.3, 36):
            c = ColumnDefinition()
            c.Width = GridLength(breite) if breite >= 30 else GridLength(breite, GridUnitType.Star)
            g.ColumnDefinitions.Add(c)

    def _zeile(self, x):
        rahmen = Border()
        rahmen.BorderBrush = LINIE
        rahmen.BorderThickness = Thickness(0, 0, 0, 1)
        rahmen.Padding = Thickness(0, 8, 0, 8)
        g = Grid()
        self._spalten(g)
        rahmen.Child = g

        def platz(el, spalte):
            Grid.SetColumn(el, spalte)
            el.Margin = Thickness(0, 0, 8, 0)
            el.VerticalAlignment = VerticalAlignment.Center
            g.Children.Add(el)

        aktiv = CheckBox()
        aktiv.IsChecked = x.get("aktiv", True)
        aktiv.ToolTip = "Beim nächsten Export mitnehmen"
        aktiv.Click += lambda s, a: self._setzen(x, "aktiv", bool(s.IsChecked))
        platz(aktiv, 0)

        ansicht = ComboBox()
        ansicht.ItemsSource = self.ansichten
        ansicht.SelectedItem = x.get("ansicht") if x.get("ansicht") in self.ansichten else None
        ansicht.ToolTip = "3D-Ansicht in Revit – exportiert wird, was dort sichtbar ist"
        ansicht.SelectionChanged += lambda s, a: self._setzen(x, "ansicht", s.SelectedItem, neu_zeichnen=True)
        platz(ansicht, 1)

        name = TextBox()
        name.Text = x.get("name") or ""
        name.ToolTip = "So heißt das Modell in der Seitenleiste des Viewers"
        name.LostFocus += lambda s, a: self._setzen(x, "name", s.Text.strip() or x.get("ansicht") or "Modell")
        platz(name, 2)

        inhalt = ComboBox()
        inhalt.ItemsSource = [t for _, t in INHALT]
        schluessel = [k for k, _ in INHALT]
        inhalt.SelectedIndex = schluessel.index(x.get("inhalt") or EIGEN)
        links = self.links_je_ansicht.get(x.get("ansicht"))
        if links is None:
            zusatz = ""
        elif links:
            zusatz = "\nVerknüpfungen in der Ansicht: %s" % ", ".join(links)
        else:
            zusatz = "\nKeine Verknüpfung in der Ansicht sichtbar."
        inhalt.ToolTip = INHALT_HILFE[x.get("inhalt") or EIGEN] + zusatz
        inhalt.SelectionChanged += lambda s, a: self._setzen(x, "inhalt", schluessel[s.SelectedIndex], neu_zeichnen=True)
        platz(inhalt, 3)

        fmt = ComboBox()
        fmt.ItemsSource = [f.upper() for f in FORMATE]
        fmt.SelectedIndex = FORMATE.index(x.get("format") or aktionen.FBX)
        fmt.ToolTip = "FBX: schnell. IFC: mit Eigenschaftssätzen, langsam – nur für „Nur dieses Modell“."
        fmt.SelectionChanged += lambda s, a: self._setzen(x, "format", FORMATE[s.SelectedIndex], neu_zeichnen=True)
        platz(fmt, 4)

        letzte = TextBlock()
        l = x.get("letzte") or {}
        letzte.Text = l.get("zeit") or "noch nie"
        letzte.Foreground = GRAU
        letzte.ToolTip = ", ".join(l.get("modelle") or []) or "Noch nicht exportiert"
        platz(letzte, 5)

        weg = Button()
        weg.Content = "✕"
        weg.Padding = Thickness(6, 2, 6, 2)
        weg.ToolTip = "Zeile entfernen (die schon veröffentlichten Modelle bleiben im Viewer)"
        weg.Click += lambda s, a: self._zeile_weg(x)
        platz(weg, 6)

        if (x.get("format") == aktionen.IFC) and (x.get("inhalt") or EIGEN) != EIGEN:
            fmt.BorderBrush = ROT
            fmt.ToolTip = "IFC geht nur mit „Nur dieses Modell“ – bitte FBX wählen."
        return rahmen

    def _setzen(self, x, feld, wert, neu_zeichnen=False):
        if x.get(feld) == wert:
            return
        x[feld] = wert
        if feld == "ansicht" and (not x.get("name") or x["name"] in self.ansichten):
            x["name"] = wert
        self._sichern()
        if neu_zeichnen:
            self.zeichnen()

    def _zeile_neu(self):
        belegt = set(x.get("ansicht") for x in self.exporte)
        frei = [a for a in self.ansichten if a not in belegt]
        if not frei and not self.ansichten:
            self.melden("Im Modell gibt es keine 3D-Ansicht.", fehler=True)
            return
        a = (frei or self.ansichten)[0]
        self.exporte.append(neu(a, a))
        self._sichern()
        self.zeichnen()

    def _zeile_weg(self, x):
        self.exporte = [e for e in self.exporte if e["id"] != x["id"]]
        self._sichern()
        self.zeichnen()

    # ---------------------------------------------------------------- Export

    def exportieren(self):
        aktiv = [x for x in self.exporte if x.get("aktiv", True) and x.get("ansicht")]
        if not aktiv:
            self.melden("Keine Zeile angehakt.", fehler=True)
            return
        falsch = [x["name"] for x in aktiv if x.get("format") == aktionen.IFC and (x.get("inhalt") or EIGEN) != EIGEN]
        if falsch:
            self.melden("IFC geht nur mit „Nur dieses Modell“: %s" % ", ".join(falsch), fehler=True)
            return
        erzwingen = bool(self.m_erzwingen.IsChecked)
        einst = self.einst

        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            pruefset = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
            vorhanden = ansichten_3d(doc)
            arbeit = []
            for x in aktiv:
                v = vorhanden.get(x["ansicht"])
                if v is None:
                    self.melden("3D-Ansicht „%s“ gibt es nicht mehr." % x["ansicht"], fehler=True)
                    return
                for z in ziele(doc, einst, x, v):
                    arbeit.append((x, v, z))
            if not arbeit:
                self.melden("In den gewählten Ansichten ist keine Verknüpfung sichtbar.", fehler=True)
                return
            schritte = []
            for x, v, z in arbeit:
                schritte += ["%s: Bauteile sammeln" % z["name"], "%s: %s-Export durch Revit" % (z["name"], x["format"].upper()),
                             "%s: in den Projektordner kopieren" % z["name"]]
            fertig, uebersprungen = [], []
            with Fortschritt("Modelle zum Viewer", schritte) as fs:
                for i, (x, v, z) in enumerate(arbeit):
                    s0 = 3 * i
                    version = version_mit_links(doc, z["links"]) if z["eigen"] else \
                        version_mit_links(z["links"][0].GetLinkDocument(), [])
                    konfig = json.dumps([x["ansicht"], x.get("inhalt"), x["format"], z["kuerzel"]])
                    stand = (x.get("letzte") or {}).get("stand", {}).get(z["kuerzel"])
                    if not erzwingen and stand == [version, konfig] and not (z["eigen"] and doc.IsModified):
                        for k in range(3):
                            fs.ueberspringen(s0 + k, "unverändert")
                        uebersprungen.append(z["name"])
                        continue
                    fs.schritt(s0, "Ansicht „%s“" % v.Name)
                    teile = []
                    if z["eigen"]:
                        teile.append(aktionen.bauteil_infos(doc, v, pruefset, fortschritt=lambda a, b: fs.menge(a, b, "Bauteile")))
                    for l in z["links"]:
                        fs.detail("Verknüpfung %s …" % link_titel(l))
                        teile.append(aktionen.link_infos(doc, v, l, fortschritt=lambda a, b: fs.menge(a, b, "Bauteile")))
                    zusatz = aktionen.infos_vereinen(teile) if x["format"] == aktionen.FBX else None
                    fs.schritt(s0 + 1, "Revit exportiert – das kann einige Minuten dauern. Revit reagiert so lange nicht.")
                    tmp = tempfile.mkdtemp(prefix="dbk_export_")
                    try:
                        start = time.time()
                        if x["format"] == aktionen.FBX:
                            pfad = aktionen.fbx_aus_ansicht(doc, v, tmp, "export.fbx", pruefset, verstecken=z["verstecken"])
                        else:
                            pfad = aktionen.ifc_aus_ansicht(doc, v, tmp, "export.ifc", pruefset, verstecken=z["verstecken"])
                        dauer = int(time.time() - start)
                        fs.schritt(s0 + 2, "%.0f MB in %d:%02d min exportiert" % (os.path.getsize(pfad) / 1e6, dauer // 60, dauer % 60))
                        quelle = "%s (%s)" % (doc.Title, v.Name) if z["eigen"] else link_titel(z["links"][0])
                        aktionen.datei_veroeffentlichen(doc, einst, pfad, z["kuerzel"], quelle, x["format"],
                                                        geschosse=pruefset.get("geschosse"), zusatz=zusatz,
                                                        version=version, name=z["name"],
                                                        fortschritt=lambda a, b: fs.menge(a, b, "MB"))
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
                    l = x.setdefault("letzte", {})
                    l.setdefault("stand", {})[z["kuerzel"]] = [version, konfig]
                    l["zeit"] = time.strftime("%d.%m.%Y %H:%M")
                    l["modelle"] = sorted(set((l.get("modelle") or []) + [z["name"]]))
                    self._sichern()
                    fertig.append(z["name"])
                fs.fertig()
            self.zeichnen()
            text = "%d Modell(e) im Viewer aktualisiert" % len(fertig)
            if uebersprungen:
                text += ", %d unverändert übersprungen" % len(uebersprungen)
            self.melden(text + ".")
        self.auftrag("Modelle exportieren", f)

    def _viewer(self):
        try:
            viewer_start.oeffnen(self.einst["projektordner"])
        except Exception as e:
            self.melden("Viewer konnte nicht gestartet werden: %s" % e, fehler=True)


def zeigen(doc):
    fenster = ModelleFenster(doc)
    fenster.show()
    return fenster
