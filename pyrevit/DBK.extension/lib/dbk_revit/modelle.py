# -*- coding: utf-8 -*-
"""Reiter „Ansichten“: 3D-Ansichten als Modelle (FBX/IFC) und 2D-Ansichten als Pläne (PNG mit Lage)
in den Projektordner stellen – für den Viewer.

3D: eine Zeile je Export – welche 3D-Ansicht, Name im Viewer, was mit Verknüpfungen passiert
(eigenes Modell und jede Verknüpfung einzeln / alles in einem / nur das eigene Modell), Format.
Die Durchbruch-Familien aus dem Prüfset werden standardmäßig weggelassen – sie kommen als Stände
mit Status über „Einreichen“.

2D: Grundrisse und Schnitte mit allen Beschriftungen als Bild; die Lage (vier Ecken in Revit-
Koordinaten) steht im Ereignis, der Viewer legt den Plan passgenau über das Modell.

Gespeichert werden die Listen im Prüfset der eigenen Firma, je Modellkürzel.
"""
from __future__ import unicode_literals

import json
import os
import shutil
import tempfile
import time
import uuid

import System
from System.Windows import Thickness, GridLength, GridUnitType, VerticalAlignment
from System.Windows.Controls import (Border, Button, CheckBox, ColumnDefinition, ComboBox, Grid, TextBlock,
                                     TextBox)
from System.Windows.Media import SolidColorBrush, ColorConverter
from Autodesk.Revit import DB

from . import aktionen, einstellungen, sammeln
from .fortschritt import Fortschritt

ALLES, EIGEN, JE_LINK = "alles", "eigen", "links"
INHALT = [(JE_LINK, "Modell + Verknüpfungen einzeln"), (ALLES, "Alles in einem Modell"), (EIGEN, "Nur dieses Modell")]
INHALT_HILFE = {
    JE_LINK: "Alles, was in der Ansicht sichtbar ist: das eigene Modell und jede sichtbare Verknüpfung "
             "als eigenes Modell im Viewer (dort einzeln ein-/ausblendbar).",
    ALLES: "Alles, was in der Ansicht sichtbar ist, als ein einziges Modell im Viewer.",
    EIGEN: "Nur Elemente dieses Revit-Modells, Verknüpfungen werden für den Export ausgeblendet.",
}
OHNE_DURCH = "viewer_ohne_durchbrueche"
FORMATE = [aktionen.FBX, aktionen.IFC]


def _pinsel(farbe):
    b = SolidColorBrush(ColorConverter.ConvertFromString(farbe))
    b.Freeze()
    return b


ROT, GRAU, LINIE = _pinsel("#be0a26"), _pinsel("#71717a"), _pinsel("#e4e4e7")


# ------------------------------------------------------------------ Logik ohne Fenster

def _schluessel(einst):
    """Je Revit-Modell (Kürzel) eine eigene Exportliste – eine Firma kann mehrere Modelle im Projekt haben."""
    return "viewer_exporte:%s" % (einst.get("modellkuerzel") or "")


def laden(einst):
    ps = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
    return ps.get(_schluessel(einst), ps.get("viewer_exporte", []))


def speichern(einst, exporte):
    ps = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
    ps[_schluessel(einst)] = exporte
    sammeln.pruefset_speichern(einst["projektordner"], einst["firma"], ps)


def neu(ansicht, name):
    return {"id": uuid.uuid4().hex[:8], "ansicht": ansicht, "name": name, "inhalt": JE_LINK,
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
    ergebnis = [{"kuerzel": modell_kuerzel(einst, x["name"]), "name": x["name"],
                 "verstecken": [l.Id for l in links], "eigen": True, "links": []}]
    host = None
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


# ------------------------------------------------------------------ 2D-Pläne (Logik)

def _plan_schluessel(einst):
    return "viewer_plaene:%s" % (einst.get("modellkuerzel") or "")


def plaene_laden(einst):
    return sammeln.pruefset_laden(einst["projektordner"], einst["firma"]).get(_plan_schluessel(einst), [])


def plaene_speichern(einst, plaene):
    ps = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
    ps[_plan_schluessel(einst)] = plaene
    sammeln.pruefset_speichern(einst["projektordner"], einst["firma"], ps)


def plan_neu(ansicht):
    return {"id": uuid.uuid4().hex[:8], "ansicht": ansicht, "name": ansicht, "aktiv": True}


def plan_kuerzel(einst, name):
    return modell_kuerzel(einst, "PLAN " + name)


# ------------------------------------------------------------------ Baustein für den Reiter „Ansichten“

class Ansichten(object):
    """Reiter „Ansichten“ im Werkzeug: 3D-Ansichten als Modelle, 2D-Ansichten als Pläne für den Viewer.

    ``fenster`` liefert die Bedienelemente (a_zeilen, a_neu, a_plaene, a_plan_neu, a_los, a_erzwingen,
    a_ohne_durch, a_hilfe_durch, a_hilfe_fbx, a_hilfe_ifc) und auftrag()/melden()/log().
    """

    def __init__(self, fenster, doc):
        self.f = fenster
        self.ansichten = sorted(ansichten_3d(doc))
        self.plan_ansichten = sorted(aktionen.plan_ansichten(doc))
        self.links_je_ansicht = {}
        self.exporte, self.plaene = [], []
        f = fenster
        f.a_neu.Click += lambda s, a: self._zeile_neu()
        f.a_plan_neu.Click += lambda s, a: self._plan_neu()
        f.a_los.Click += lambda s, a: self.exportieren()
        f.a_ohne_durch.Click += lambda s, a: self._ohne_durch_setzen(bool(s.IsChecked))
        f.a_hilfe_fbx.Text = aktionen.FORMAT_TEXT[aktionen.FBX]
        f.a_hilfe_ifc.Text = aktionen.FORMAT_TEXT[aktionen.IFC]
        self._doc = doc

    @property
    def einst(self):
        return self.f.einst

    def laden(self):
        """Nach dem Einrichten des Projekts: Listen aus dem Prüfset lesen und zeichnen."""
        if not einstellungen.vollstaendig(self.einst):
            self.exporte, self.plaene = [], []
            self.zeichnen()
            return
        alle = ansichten_3d(self._doc)
        self.exporte = laden(self.einst)
        self.plaene = plaene_laden(self.einst)
        for x in self.exporte:
            if x.get("ansicht") in alle and x["ansicht"] not in self.links_je_ansicht:
                self.links_je_ansicht[x["ansicht"]] = [link_titel(l) for l in sichtbare_links(self._doc, alle[x["ansicht"]])]
        if not self.exporte:
            aktiv = self._doc.ActiveView
            start = aktiv.Name if isinstance(aktiv, DB.View3D) and aktiv.Name in self.ansichten else \
                (self.ansichten[0] if self.ansichten else None)
            if start:
                self.exporte = [neu(start, self.einst.get("modellkuerzel") or self._doc.Title)]
        ps = sammeln.pruefset_laden(self.einst["projektordner"], self.einst["firma"])
        familien = sorted(set(t["familie"] for t in ps.get("typen") or []))
        self.f.a_ohne_durch.IsChecked = ps.get(OHNE_DURCH, True)
        if familien:
            self.f.a_hilfe_durch.Text = ("Durchbruch-Familien im eigenen Modell weglassen – sie kommen als Stände mit "
                                         "Prüfstatus über „Einreichen“ in den Viewer (zurzeit %d: %s)."
                                         % (len(familien), ", ".join(familien[:4]) + (" …" if len(familien) > 4 else "")))
        else:
            self.f.a_hilfe_durch.Text = ("Durchbruch-Familien weglassen – zurzeit sind keine festgelegt "
                                         "(Reiter „Durchbrüche“ › Familien in der Koordination).")
        self.zeichnen()

    def _sichern(self):
        if einstellungen.vollstaendig(self.einst):
            speichern(self.einst, self.exporte)
            plaene_speichern(self.einst, self.plaene)

    def _ohne_durch_setzen(self, an):
        ps = sammeln.pruefset_laden(self.einst["projektordner"], self.einst["firma"])
        ps[OHNE_DURCH] = an
        sammeln.pruefset_speichern(self.einst["projektordner"], self.einst["firma"], ps)

    # ---------------------------------------------------------------- Zeilen

    def zeichnen(self):
        f = self.f
        f.a_zeilen.Children.Clear()
        if not self.exporte:
            f.a_zeilen.Children.Add(self._leer("Noch keine 3D-Ansicht – „+ 3D-Ansicht“."))
        for x in self.exporte:
            f.a_zeilen.Children.Add(self._zeile(x))
        f.a_plaene.Children.Clear()
        if not self.plaene:
            f.a_plaene.Children.Add(self._leer("Noch kein Plan – „+ Grundriss / Schnitt“. Beschriftungen, Bemaßung und "
                                               "Achsen erscheinen im Viewer passgenau über dem Modell."))
        for x in self.plaene:
            f.a_plaene.Children.Add(self._plan_zeile(x))

    @staticmethod
    def _leer(text):
        t = TextBlock()
        t.Text = text
        t.Foreground = GRAU
        t.TextWrapping = System.Windows.TextWrapping.Wrap
        t.Margin = Thickness(4, 8, 4, 8)
        return t

    @staticmethod
    def _raster(breiten):
        rahmen = Border()
        rahmen.BorderBrush = LINIE
        rahmen.BorderThickness = Thickness(0, 0, 0, 1)
        rahmen.Padding = Thickness(0, 6, 0, 6)
        g = Grid()
        for breite in breiten:
            c = ColumnDefinition()
            c.Width = GridLength(breite) if breite >= 30 else GridLength(breite, GridUnitType.Star)
            g.ColumnDefinitions.Add(c)
        rahmen.Child = g

        def platz(el, spalte):
            Grid.SetColumn(el, spalte)
            el.Margin = Thickness(0, 0, 8, 0)
            el.VerticalAlignment = VerticalAlignment.Center
            g.Children.Add(el)
        return rahmen, platz

    def _gemeinsam(self, x, platz, liste, spalten_letzte, spalte_weg, hinweis):
        aktiv = CheckBox()
        aktiv.IsChecked = x.get("aktiv", True)
        aktiv.ToolTip = "Beim nächsten Export mitnehmen"
        aktiv.Click += lambda s, a: self._setzen(x, "aktiv", bool(s.IsChecked))
        platz(aktiv, 0)
        letzte = TextBlock()
        l = x.get("letzte") or {}
        letzte.Text = l.get("zeit") or "noch nie"
        letzte.Foreground = GRAU
        letzte.ToolTip = ", ".join(l.get("modelle") or []) or "Noch nicht exportiert"
        platz(letzte, spalten_letzte)
        weg = Button()
        weg.Content = "✕"
        weg.Padding = Thickness(6, 2, 6, 2)
        weg.ToolTip = hinweis
        weg.Click += lambda s, a: self._zeile_weg(liste, x)
        platz(weg, spalte_weg)

    def _zeile(self, x):
        rahmen, platz = self._raster((30, 2.2, 1.8, 1.8, 0.9, 1.3, 36))
        self._gemeinsam(x, platz, "exporte", 5, 6, "Zeile entfernen (schon veröffentlichte Modelle bleiben im Viewer)")
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
        zusatz = "" if links is None else ("\nVerknüpfungen in der Ansicht: %s" % ", ".join(links) if links
                                           else "\nKeine Verknüpfung in der Ansicht sichtbar.")
        inhalt.ToolTip = INHALT_HILFE[x.get("inhalt") or EIGEN] + zusatz
        inhalt.SelectionChanged += lambda s, a: self._setzen(x, "inhalt", schluessel[s.SelectedIndex], neu_zeichnen=True)
        platz(inhalt, 3)
        fmt = ComboBox()
        fmt.ItemsSource = [f.upper() for f in FORMATE]
        fmt.SelectedIndex = FORMATE.index(x.get("format") or aktionen.FBX)
        fmt.ToolTip = "FBX: schnell. IFC: mit Eigenschaftssätzen, langsam – nur für „Nur dieses Modell“."
        fmt.SelectionChanged += lambda s, a: self._setzen(x, "format", FORMATE[s.SelectedIndex], neu_zeichnen=True)
        platz(fmt, 4)
        if (x.get("format") == aktionen.IFC) and (x.get("inhalt") or EIGEN) != EIGEN:
            fmt.BorderBrush = ROT
            fmt.ToolTip = "IFC geht nur mit „Nur dieses Modell“ – bitte FBX wählen."
        return rahmen

    def _plan_zeile(self, x):
        rahmen, platz = self._raster((30, 2.6, 2.4, 1.3, 36))
        self._gemeinsam(x, platz, "plaene", 3, 4, "Zeile entfernen (schon veröffentlichte Pläne bleiben im Viewer)")
        ansicht = ComboBox()
        ansicht.ItemsSource = self.plan_ansichten
        ansicht.SelectedItem = x.get("ansicht") if x.get("ansicht") in self.plan_ansichten else None
        ansicht.ToolTip = "Grundriss oder Schnitt in Revit – mit allen Beschriftungen, so wie die Ansicht aussieht"
        ansicht.SelectionChanged += lambda s, a: self._setzen(x, "ansicht", s.SelectedItem, neu_zeichnen=True)
        platz(ansicht, 1)
        name = TextBox()
        name.Text = x.get("name") or ""
        name.ToolTip = "So heißt der Plan in der Seitenleiste des Viewers"
        name.LostFocus += lambda s, a: self._setzen(x, "name", s.Text.strip() or x.get("ansicht") or "Plan")
        platz(name, 2)
        return rahmen

    def _setzen(self, x, feld, wert, neu_zeichnen=False):
        if x.get(feld) == wert:
            return
        alt = x.get(feld)
        x[feld] = wert
        if feld == "ansicht" and (not x.get("name") or x["name"] == alt):
            x["name"] = wert
        self._sichern()
        if neu_zeichnen:
            self.zeichnen()

    def _zeile_neu(self):
        belegt = set(x.get("ansicht") for x in self.exporte)
        frei = [a for a in self.ansichten if a not in belegt]
        if not self.ansichten:
            self.f.melden("Im Modell gibt es keine 3D-Ansicht.", fehler=True)
            return
        a = (frei or self.ansichten)[0]
        self.exporte.append(neu(a, a))
        self._sichern()
        self.zeichnen()

    def _plan_neu(self):
        if not self.plan_ansichten:
            self.f.melden("Im Modell gibt es keinen Grundriss oder Schnitt.", fehler=True)
            return
        belegt = set(x.get("ansicht") for x in self.plaene)
        aktiv = self._doc.ActiveView
        vorschlag = aktiv.Name if aktiv is not None and aktiv.Name in self.plan_ansichten and aktiv.Name not in belegt else None
        frei = [a for a in self.plan_ansichten if a not in belegt]
        self.plaene.append(plan_neu(vorschlag or (frei or self.plan_ansichten)[0]))
        self._sichern()
        self.zeichnen()

    def _zeile_weg(self, liste, x):
        setattr(self, liste, [e for e in getattr(self, liste) if e["id"] != x["id"]])
        self._sichern()
        self.zeichnen()

    # ---------------------------------------------------------------- Export

    def exportieren(self):
        aktiv = [x for x in self.exporte if x.get("aktiv", True) and x.get("ansicht")]
        plaene = [x for x in self.plaene if x.get("aktiv", True) and x.get("ansicht")]
        if not aktiv and not plaene:
            self.f.melden("Keine Zeile angehakt.", fehler=True)
            return
        falsch = [x["name"] for x in aktiv if x.get("format") == aktionen.IFC and (x.get("inhalt") or EIGEN) != EIGEN]
        if falsch:
            self.f.melden("IFC geht nur mit „Nur dieses Modell“: %s" % ", ".join(falsch), fehler=True)
            return
        erzwingen = bool(self.f.a_erzwingen.IsChecked)
        ohne_durch = bool(self.f.a_ohne_durch.IsChecked)
        einst = self.einst

        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            pruefset = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
            vorhanden = ansichten_3d(doc)
            plan_vorhanden = aktionen.plan_ansichten(doc)
            arbeit = []
            for x in aktiv:
                v = vorhanden.get(x["ansicht"])
                if v is None:
                    self.f.melden("3D-Ansicht „%s“ gibt es nicht mehr." % x["ansicht"], fehler=True)
                    return
                for z in ziele(doc, einst, x, v):
                    arbeit.append(("3d", x, v, z))
            for x in plaene:
                v = plan_vorhanden.get(x["ansicht"])
                if v is None:
                    self.f.melden("Ansicht „%s“ gibt es nicht mehr." % x["ansicht"], fehler=True)
                    return
                arbeit.append(("2d", x, v, {"kuerzel": plan_kuerzel(einst, x["name"]), "name": x["name"],
                                            "eigen": True, "links": []}))
            schritte = []
            for art, x, v, z in arbeit:
                if art == "3d":
                    schritte += ["%s: Bauteile sammeln" % z["name"], "%s: %s-Export durch Revit" % (z["name"], x["format"].upper()),
                                 "%s: in den Projektordner kopieren" % z["name"]]
                else:
                    schritte += ["Plan %s: Bild aus Revit" % z["name"], "Plan %s: in den Projektordner" % z["name"]]
            fertig, uebersprungen = [], []
            with Fortschritt("Ansichten zum Viewer", schritte) as fs:
                s0 = 0
                for art, x, v, z in arbeit:
                    if art == "2d":
                        s0 = self._plan_exportieren(doc, einst, x, v, z, fs, s0, erzwingen, fertig, uebersprungen)
                    else:
                        s0 = self._modell_exportieren(doc, einst, pruefset, x, v, z, fs, s0, erzwingen, ohne_durch,
                                                      fertig, uebersprungen)
                fs.fertig()
            self.zeichnen()
            text = "%d Ansicht(en) im Viewer aktualisiert" % len(fertig)
            if uebersprungen:
                text += ", %d unverändert übersprungen" % len(uebersprungen)
            self.f.melden(text + ".")
            self.f.log(text + (": " + ", ".join(fertig) if fertig else "") + ".")
        self.f.auftrag("Ansichten exportieren", f)

    def _vermerken(self, x, z, version, konfig, fertig):
        l = x.setdefault("letzte", {})
        l.setdefault("stand", {})[z["kuerzel"]] = [version, konfig]
        l["zeit"] = time.strftime("%d.%m.%Y %H:%M")
        l["modelle"] = sorted(set((l.get("modelle") or []) + [z["name"]]))
        self._sichern()
        fertig.append(z["name"])

    def _modell_exportieren(self, doc, einst, pruefset, x, v, z, fs, s0, erzwingen, ohne_durch, fertig, uebersprungen):
        version = version_mit_links(doc, z["links"]) if z["eigen"] else version_mit_links(z["links"][0].GetLinkDocument(), [])
        konfig = json.dumps([x["ansicht"], x.get("inhalt"), x["format"], z["kuerzel"],
                             ohne_durch if z["eigen"] else None, aktionen.FBX_DETAIL])
        weglassen = pruefset if (z["eigen"] and ohne_durch) else None
        stand = (x.get("letzte") or {}).get("stand", {}).get(z["kuerzel"])
        if not erzwingen and stand == [version, konfig] and not (z["eigen"] and doc.IsModified):
            for k in range(3):
                fs.ueberspringen(s0 + k, "unverändert")
            uebersprungen.append(z["name"])
            return s0 + 3
        fs.schritt(s0, "Ansicht „%s“" % v.Name)
        teile = []
        if z["eigen"]:
            teile.append(aktionen.bauteil_infos(doc, v, weglassen, fortschritt=lambda a, b: fs.menge(a, b, "Bauteile")))
        for l in z["links"]:
            fs.detail("Verknüpfung %s …" % link_titel(l))
            teile.append(aktionen.link_infos(doc, v, l, fortschritt=lambda a, b: fs.menge(a, b, "Bauteile")))
        zusatz = aktionen.infos_vereinen(teile) if x["format"] == aktionen.FBX else None
        fs.schritt(s0 + 1, "Revit exportiert – das kann einige Minuten dauern. Revit reagiert so lange nicht.")
        tmp = tempfile.mkdtemp(prefix="dbk_export_")
        try:
            start = time.time()
            if x["format"] == aktionen.FBX:
                pfad = aktionen.fbx_aus_ansicht(doc, v, tmp, "export.fbx", weglassen, verstecken=z["verstecken"])
            else:
                pfad = aktionen.ifc_aus_ansicht(doc, v, tmp, "export.ifc", weglassen, verstecken=z["verstecken"])
            dauer = int(time.time() - start)
            fs.schritt(s0 + 2, "%.0f MB in %d:%02d min exportiert" % (os.path.getsize(pfad) / 1e6, dauer // 60, dauer % 60))
            quelle = "%s (%s)" % (doc.Title, v.Name) if z["eigen"] else link_titel(z["links"][0])
            aktionen.datei_veroeffentlichen(doc, einst, pfad, z["kuerzel"], quelle, x["format"],
                                            geschosse=pruefset.get("geschosse"), zusatz=zusatz,
                                            version=version, name=z["name"],
                                            fortschritt=lambda a, b: fs.menge(a, b, "MB"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._vermerken(x, z, version, konfig, fertig)
        return s0 + 3

    def _plan_exportieren(self, doc, einst, x, v, z, fs, s0, erzwingen, fertig, uebersprungen):
        version = aktionen.modell_version(doc) or "?"
        konfig = json.dumps([x["ansicht"], z["kuerzel"], aktionen.PLAN_PIXEL])
        stand = (x.get("letzte") or {}).get("stand", {}).get(z["kuerzel"])
        if not erzwingen and stand == [version, konfig] and not doc.IsModified:
            for k in range(2):
                fs.ueberspringen(s0 + k, "unverändert")
            uebersprungen.append(z["name"])
            return s0 + 2
        fs.schritt(s0, "„%s“ als Bild" % v.Name)
        tmp = tempfile.mkdtemp(prefix="dbk_plan_")
        try:
            pfad, plan = aktionen.plan_aus_ansicht(doc, v, tmp)
            plan["ansicht"] = v.Name
            fs.schritt(s0 + 1, "%.1f MB" % (os.path.getsize(pfad) / 1e6))
            aktionen.datei_veroeffentlichen(doc, einst, pfad, z["kuerzel"], "%s (%s)" % (doc.Title, v.Name), aktionen.PNG,
                                            version=version, name=z["name"], plan=plan)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._vermerken(x, z, version, konfig, fertig)
        return s0 + 2
