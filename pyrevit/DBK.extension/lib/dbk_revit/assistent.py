# -*- coding: utf-8 -*-
"""Einreichen-Assistent: nicht-modales Fenster mit drei Schritten (Pakete · Prüfen · Einreichen).

Alles, was die Revit-API braucht, läuft über ein ExternalEvent (Warteschlange),
damit das Fenster offen bleiben kann, während man in Revit arbeitet.
"""
from __future__ import unicode_literals

import os
import shutil
import tempfile
import time
import traceback

from System.Windows import Visibility
from System.Windows.Controls import CheckBox, TreeViewItem
from Autodesk.Revit import UI
from pyrevit import forms

from . import aktionen, ansichten, pakete, sammeln, viewer_start
from .sammeln import eid

XAML = os.path.join(os.path.dirname(__file__), "ui", "assistent.xaml")
ART = {pakete.DURCHBRUECHE: "Durchbrüche", pakete.TGA: "TGA-Modell → IFC"}


class _Warteschlange(UI.IExternalEventHandler):
    def __init__(self, fenster):
        self.fenster = fenster
        self.auftraege = []

    def Execute(self, uiapp):
        while self.auftraege:
            titel, f = self.auftraege.pop(0)
            try:
                f(uiapp)
            except Exception as e:
                self.fenster.melden("Fehler bei „%s“: %s" % (titel, e), fehler=True)
                self.fenster.log("FEHLER %s\n%s" % (titel, traceback.format_exc()))
        self.fenster.beschaeftigt(False)

    def GetName(self):
        return "DBK Einreichen"


class Zeile(object):
    def __init__(self, p, umfang):
        self.id = p["id"]
        self.name = ("✓ " if p.get("aktiv", True) else "   ") + p["name"]
        self.art = ART[p["art"]]
        self.filter = pakete.filter_text(p)
        self.umfang = umfang


class Assistent(forms.WPFWindow):

    def __init__(self, einst):
        forms.WPFWindow.__init__(self, XAML)
        self.einst = einst
        self.ordner, self.firma = einst["projektordner"], einst["firma"]
        self.pruefset = sammeln.pruefset_laden(self.ordner, self.firma)
        self.pakete = pakete.laden(self.ordner, self.firma)
        self.plan = None
        self.ebenen_doc = []
        self.tga_umfang = {}        # Paket-ID -> Anzahl sichtbarer Bauteile
        self.auswahl_id = None
        self._baum_boxen = {}
        self._handler = _Warteschlange(self)
        self._ereignis = UI.ExternalEvent.Create(self._handler)

        self.kopf.Text = "%s · %s · %s · Modell %s" % (einst["name"], einst["rolle"], einst["firma"], einst["modellkuerzel"])
        self.r_runde.Text = "Prüfrunde %s" % time.strftime("%d.%m.%Y")

        self.k_einlesen.Click += lambda s, a: self.einlesen()
        self.liste.SelectionChanged += self._liste_gewaehlt
        self.k_neu_db.Click += lambda s, a: self._neu(pakete.DURCHBRUECHE)
        self.k_neu_tga.Click += lambda s, a: self._neu(pakete.TGA)
        self.k_entfernen.Click += lambda s, a: self._entfernen()
        self.k_speichern.Click += lambda s, a: self._editor_speichern()
        self.k_3d.Click += lambda s, a: self._3d(self._paket(self.auswahl_id), aus_editor=True)
        self.p_paket.SelectionChanged += lambda s, a: self._baum_zeichnen()
        self.p_suche.TextChanged += lambda s, a: self._baum_filtern()
        self.p_alle.Click += lambda s, a: self._baum_setzen(lambda oid: True)
        self.p_keine.Click += lambda s, a: self._baum_setzen(lambda oid: False)
        self.p_vorschlag.Click += lambda s, a: self._baum_setzen(
            lambda oid: self.plan.zustand[oid] != aktionen.UNVERAENDERT)
        self.p_revit.Click += lambda s, a: self._revit_auswahl()
        self.p_aus_ansicht.Click += lambda s, a: self._aus_ansicht()
        self.p_3d.Click += lambda s, a: self._3d(self._pruef_paket())
        self.tabs.SelectionChanged += self._tab_gewechselt
        self.k_los.Click += lambda s, a: self._los()
        self.k_viewer.Click += lambda s, a: self._viewer()

        self.einlesen()

    # ------------------------------------------------------------ Hilfen

    def auftrag(self, titel, f):
        self._handler.auftraege.append((titel, f))
        self.beschaeftigt(True, titel)
        self._ereignis.Raise()

    def beschaeftigt(self, an, titel=None):
        self.Cursor = __import__("System").Windows.Input.Cursors.Wait if an else None
        if an and titel:
            self.melden("%s …" % titel)

    def melden(self, text, fehler=False):
        self.meldung.Text = text
        self.meldung.Foreground = __import__("System").Windows.Media.Brushes.DarkRed if fehler else \
            __import__("System").Windows.Media.Brushes.DimGray

    def log(self, text):
        self.r_log.AppendText("%s  %s\n" % (time.strftime("%H:%M:%S"), text))
        self.r_log.ScrollToEnd()

    def _paket(self, pid):
        return next((p for p in self.pakete if p["id"] == pid), None)

    def _speichern(self):
        pakete.speichern(self.ordner, self.firma, self.pakete)

    # ------------------------------------------------------------ Einlesen

    def einlesen(self):
        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            self.pruefset = sammeln.pruefset_laden(self.ordner, self.firma)
            self.plan = aktionen.einreichen_planen(doc, self.einst, self.pruefset)
            self.ebenen_doc = [e["name"] for e in sammeln.ebenen(doc)]
            self.melden("%d Durchbrüche im Prüfset: %d neu, %d verschoben/geändert, %d unverändert."
                        % (len(self.plan.objekte), len(self.plan.neu), len(self.plan.geometrie), self.plan.unveraendert))
            self.alles_zeichnen()
        self.auftrag("Durchbrüche einlesen", f)

    def alles_zeichnen(self):
        self._liste_zeichnen()
        self._editor_zeichnen()
        self._pruef_auswahl_zeichnen()
        self._einreichen_zeichnen()

    def _umfang(self, p):
        if self.plan is None:
            return ""
        if p["art"] == pakete.DURCHBRUECHE:
            z = pakete.zaehlen(p, self.plan)
            return "%d neu · %d geänd. · %d alt" % (z["neu"], z["geometrie"] + z["daten"], z["unveraendert"])
        n = self.tga_umfang.get(p["id"])
        return "%d Bauteile" % n if n is not None else "→ 3D zum Zählen"

    # ------------------------------------------------------------ Schritt 1: Pakete

    def _liste_zeichnen(self):
        zeilen = [Zeile(p, self._umfang(p)) for p in self.pakete]
        self.liste.ItemsSource = zeilen
        for z in zeilen:
            if z.id == self.auswahl_id:
                self.liste.SelectedItem = z

    def _liste_gewaehlt(self, sender, args):
        z = self.liste.SelectedItem
        if z is not None and z.id != self.auswahl_id:
            self.auswahl_id = z.id
            self._editor_zeichnen()

    def _neu(self, art):
        from .einstellungen import kuerzel_bereinigen
        self.einst["modellkuerzel"] = kuerzel_bereinigen(self.einst["modellkuerzel"]) or "TGA"
        anzahl = len([p for p in self.pakete if p["art"] == art]) + 1
        if art == pakete.DURCHBRUECHE:
            name, kuerzel = "Durchbrüche %d" % anzahl, "%s-DB%d" % (self.einst["modellkuerzel"], anzahl)
        else:
            name = "TGA ohne Durchbrüche" if anzahl == 1 else "TGA %d" % anzahl
            kuerzel = self.einst["modellkuerzel"] if anzahl == 1 else "%s-%d" % (self.einst["modellkuerzel"], anzahl)
        p = pakete.neu(art, name, kuerzel)
        self.pakete.append(p)
        self._speichern()
        self.auswahl_id = p["id"]
        self._liste_zeichnen()
        self._editor_zeichnen()
        self.e_name.Focus()
        self.e_name.SelectAll()

    def _entfernen(self):
        p = self._paket(self.auswahl_id)
        if p and forms.alert("Paket „%s“ entfernen? Die Revit-Ansicht bleibt bestehen." % p["name"], yes=True, no=True):
            self.pakete.remove(p)
            self._speichern()
            self.auswahl_id = None
            self.alles_zeichnen()

    def _checkliste(self, panel, eintraege, gewaehlt):
        panel.Children.Clear()
        boxen = []
        for wert, text in eintraege:
            b = CheckBox()
            b.Content = text
            b.Tag = wert
            b.IsChecked = wert in gewaehlt
            b.Margin = __import__("System").Windows.Thickness(0, 1, 0, 1)
            panel.Children.Add(b)
            boxen.append(b)
        return boxen

    def _editor_zeichnen(self):
        p = self._paket(self.auswahl_id)
        self.editor.IsEnabled = p is not None
        if p is None:
            self.e_art.Text = "Paket links auswählen oder neu anlegen"
            self.e_name.Text = self.e_kuerzel.Text = ""
            self.e_ebenen.Children.Clear()
            self.e_inhalt.Children.Clear()
            return
        self.e_art.Text = ART[p["art"]]
        self.e_name.Text = p["name"]
        self.e_kuerzel.Text = p["kuerzel"]
        self.e_ifc.Visibility = Visibility.Visible if p["art"] == pakete.DURCHBRUECHE else Visibility.Collapsed
        self.e_ifc.IsChecked = bool(p.get("auch_ifc"))
        if p["art"] == pakete.DURCHBRUECHE and self.plan is not None:
            ebenen = sorted(set(d.get("ebene") for d in self.plan.objekte.values()),
                            key=lambda n: self.ebenen_doc.index(n) if n in self.ebenen_doc else 999)
            anzahl = {}
            for d in self.plan.objekte.values():
                anzahl[d.get("ebene")] = anzahl.get(d.get("ebene"), 0) + 1
            self._e_ebenen = self._checkliste(self.e_ebenen, [(e, "%s  (%d)" % (e, anzahl[e])) for e in ebenen],
                                              set(p.get("ebenen") or []))
            self.e_inhalt_titel.Text = "Familien/Typen aus dem Prüfset (keine = alle)"
            typen = [(t["familie"], t["typ"]) for t in self.pruefset.get("typen", [])]
            self._e_inhalt = self._checkliste(self.e_inhalt, [(t, "%s : %s" % t) for t in typen],
                                              set(tuple(f) for f in (p.get("familien") or [])))
        else:
            self._e_ebenen = self._checkliste(self.e_ebenen, [(e, e) for e in self.ebenen_doc], set(p.get("ebenen") or []))
            self.e_inhalt_titel.Text = "Gewerke"
            self._e_inhalt = self._checkliste(self.e_inhalt, [(g, g) for g in pakete.GEWERK_NAMEN],
                                              set(p.get("gewerke") or []))

    def _editor_speichern(self):
        p = self._paket(self.auswahl_id)
        if p is None:
            return None
        name = (self.e_name.Text or "").strip()
        from .einstellungen import kuerzel_bereinigen
        kuerzel = kuerzel_bereinigen(self.e_kuerzel.Text)
        self.e_kuerzel.Text = kuerzel
        if not name or not kuerzel:
            self.melden("Bitte Name und Kürzel angeben.", fehler=True)
            return None
        if any(q is not p and (q["name"] == name or q["kuerzel"] == kuerzel) for q in self.pakete):
            self.melden("Name oder Kürzel gibt es schon in einem anderen Paket.", fehler=True)
            return None
        p["name"], p["kuerzel"] = name, kuerzel
        p["ebenen"] = [b.Tag for b in self._e_ebenen if b.IsChecked]
        if p["art"] == pakete.DURCHBRUECHE:
            p["familien"] = [list(b.Tag) for b in self._e_inhalt if b.IsChecked]
            p["auch_ifc"] = bool(self.e_ifc.IsChecked)
        else:
            p["gewerke"] = [b.Tag for b in self._e_inhalt if b.IsChecked]
            self.tga_umfang.pop(p["id"], None)
        self._speichern()
        self._liste_zeichnen()
        self._pruef_auswahl_zeichnen()
        self._einreichen_zeichnen()
        self.melden("Paket „%s“ gespeichert." % name)
        return p

    def _3d(self, p, aus_editor=False):
        if p is None:
            return
        if aus_editor and self._editor_speichern() is None:
            return
        if self.plan is None:
            return

        def f(uiapp):
            uidoc = uiapp.ActiveUIDocument
            v = pakete.ansicht_aufbauen(uidoc.Document, p, self.plan, self.pruefset)
            uidoc.ActiveView = v
            if p["art"] == pakete.TGA:
                kats = pakete.tga_zaehlen(uidoc.Document, p, set(eid(i) for i in self.plan.element_ids.values()))
                self.tga_umfang[p["id"]] = sum(kats.values())
                self.melden("„%s“: %d Bauteile sichtbar (%s). Durchbrüche orange – sie werden nicht exportiert. "
                            "Bereiche ausblenden, Filter oder Schnittbox in Revit einstellen – exportiert wird, was sichtbar ist."
                            % (v.Name, sum(kats.values()), ", ".join("%s %d" % kv for kv in sorted(kats.items(), key=lambda kv: -kv[1])[:5])))
            else:
                self.melden("„%s“: %d Durchbrüche (orange). Einzelne in der Ansicht ausblenden und „Aus Ansicht übernehmen“ "
                            "oder im Schritt „Prüfen“ abwählen." % (v.Name, len(pakete.objekte(p, self.plan))))
            self._liste_zeichnen()
        self.auftrag("3D-Ansicht „%s“" % p["name"], f)

    # ------------------------------------------------------------ Schritt 2: Prüfen

    def _durch_pakete(self):
        return [p for p in self.pakete if p["art"] == pakete.DURCHBRUECHE]

    def _pruef_auswahl_zeichnen(self):
        namen = [p["name"] for p in self._durch_pakete()]
        alt = self.p_paket.SelectedItem
        self.p_paket.ItemsSource = namen
        self.p_paket.SelectedItem = alt if alt in namen else (namen[0] if namen else None)

    def _pruef_paket(self):
        return next((p for p in self._durch_pakete() if p["name"] == self.p_paket.SelectedItem), None)

    def _tab_gewechselt(self, sender, args):
        if args.OriginalSource == self.tabs:
            if self.tabs.SelectedIndex == 1:
                self._baum_zeichnen()
            elif self.tabs.SelectedIndex == 2:
                self._einreichen_zeichnen()

    def _baum_zeichnen(self):
        self.p_baum.Items.Clear()
        self._baum_boxen = {}
        p = self._pruef_paket()
        if p is None or self.plan is None:
            self.p_summe.Text = "Noch kein Durchbruch-Paket – im Schritt „Pakete“ anlegen."
            return
        aus = set(p.get("aus") or [])
        gruppen = {}
        for oid in pakete.objekte(p, self.plan, mit_aus=True):
            gruppen.setdefault(self.plan.objekte[oid].get("ebene"), []).append(oid)
        for ebene in sorted(gruppen, key=lambda n: self.ebenen_doc.index(n) if n in self.ebenen_doc else 999):
            knoten = TreeViewItem()
            knoten.Header = "%s  (%d)" % (ebene, len(gruppen[ebene]))
            knoten.IsExpanded = len(gruppen) <= 2
            for oid in sorted(gruppen[ebene], key=lambda o: self.plan.objekte[o].get("nummer", "")):
                d = self.plan.objekte[oid]
                b = CheckBox()
                b.Content = "%s · %s · %s · %s" % (d.get("nummer"), d.get("typ"), d.get("groesse"),
                                                   aktionen.ZUSTAND_TEXT[self.plan.zustand[oid]])
                b.IsChecked = oid not in aus
                b.IsEnabled = self.plan.zustand[oid] != aktionen.FREMD
                b.Tag = oid
                b.Click += lambda s, a: self._baum_geaendert()
                item = TreeViewItem()
                item.Header = b
                knoten.Items.Add(item)
                self._baum_boxen[oid] = (b, item, (b.Content + " " + (d.get("familie") or "")).lower())
            self.p_baum.Items.Add(knoten)
        self._baum_summe()

    def _baum_geaendert(self):
        p = self._pruef_paket()
        if p is None:
            return
        p["aus"] = sorted(oid for oid, (b, i, t) in self._baum_boxen.items() if not b.IsChecked)
        self._speichern()
        self._baum_summe()
        self._liste_zeichnen()

    def _baum_setzen(self, regel):
        for oid, (b, i, t) in self._baum_boxen.items():
            if b.IsEnabled:
                b.IsChecked = bool(regel(oid))
        self._baum_geaendert()

    def _baum_filtern(self):
        such = (self.p_suche.Text or "").lower().strip()
        for oid, (b, item, text) in self._baum_boxen.items():
            item.Visibility = Visibility.Visible if (not such or such in text) else Visibility.Collapsed
            if such and such in text:
                item.Parent.IsExpanded = True

    def _baum_summe(self):
        n = len(self._baum_boxen)
        an = len([1 for b, i, t in self._baum_boxen.values() if b.IsChecked])
        self.p_summe.Text = "%d von %d Exemplaren ausgewählt." % (an, n)

    def _revit_auswahl(self):
        p = self._pruef_paket()
        if p is None:
            return

        def f(uiapp):
            ids = set(eid(i) for i in uiapp.ActiveUIDocument.Selection.GetElementIds())
            if not ids:
                self.melden("In Revit ist nichts markiert.", fehler=True)
                return
            self._baum_setzen(lambda oid: eid(self.plan.element_ids[oid]) in ids)
        self.auftrag("Revit-Auswahl übernehmen", f)

    def _aus_ansicht(self):
        p = self._pruef_paket()
        if p is None:
            return

        def f(uiapp):
            if pakete.aus_ansicht_uebernehmen(uiapp.ActiveUIDocument.Document, p, self.plan):
                self._speichern()
            self._baum_zeichnen()
            self._liste_zeichnen()
            self.melden("Ausgeblendete Durchbrüche aus „%s“ übernommen." % pakete.ansicht_name(p))
        self.auftrag("Aus Ansicht übernehmen", f)

    # ------------------------------------------------------------ Schritt 3: Einreichen

    def _einreichen_zeichnen(self):
        self.r_pakete.Children.Clear()
        for p in self.pakete:
            b = CheckBox()
            b.Content = "%s  –  %s  –  %s" % (p["name"], ART[p["art"]], self._umfang(p))
            b.IsChecked = bool(p.get("aktiv", True))
            b.Tag = p["id"]
            b.Margin = __import__("System").Windows.Thickness(0, 2, 0, 2)

            def umschalten(s, a, pid=p["id"]):
                q = self._paket(pid)
                q["aktiv"] = bool(s.IsChecked)
                self._speichern()
                self._liste_zeichnen()
            b.Click += umschalten
            self.r_pakete.Children.Add(b)
        n = len(self.plan.entfallen) if self.plan else 0
        self.r_entfallen.Content = "Im Modell gelöschte Durchbrüche aus der Koordination entfernen (%d)" % n
        self.r_entfallen.IsChecked = n > 0
        self.r_entfallen.IsEnabled = n > 0

    def _los(self):
        aktiv = [p for p in self.pakete if p.get("aktiv", True)]
        if not aktiv and not (self.r_entfallen.IsChecked and self.plan and self.plan.entfallen):
            self.melden("Kein Paket angehakt.", fehler=True)
            return
        runde = (self.r_runde.Text or "").strip()
        if any(p["art"] == pakete.DURCHBRUECHE for p in aktiv) and not runde:
            self.melden("Bitte einen Namen für die Prüfrunde angeben.", fehler=True)
            return
        entfallen = bool(self.r_entfallen.IsChecked)

        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            self.plan = aktionen.einreichen_planen(doc, self.einst, self.pruefset)
            auswahl = set()
            for p in aktiv:
                if p["art"] == pakete.DURCHBRUECHE:
                    if pakete.aus_ansicht_uebernehmen(doc, p, self.plan):
                        self._speichern()
                    # Unveränderte werden nicht erneut eingereicht (dafür gibt es „Erneut einreichen“ im Prüf-Manager)
                    auswahl.update(o for o in pakete.objekte(p, self.plan)
                                   if self.plan.zustand[o] != aktionen.UNVERAENDERT)
            if auswahl or entfallen:
                r = aktionen.einreichen_ausfuehren(self.einst, self.plan, rundenname=runde, auswahl=auswahl,
                                                   entfallen=entfallen)
                self.log("Durchbrüche: %d zur Prüfung eingereicht, %d Datenabgleich, %d entfernt (Runde „%s“)."
                         % (r["eingereicht"], r["geaendert"], r["geloescht"], runde))
            for p in aktiv:
                if p["art"] == pakete.TGA or p.get("auch_ifc"):
                    self.log("Exportiere „%s“ als IFC (%s) …" % (p["name"], p["kuerzel"]))
                    d = self._exportieren(doc, p)
                    self.log("  veröffentlicht: %s, %s MB" % (d["modell"], d["groesse_mb"]))
            self.plan = aktionen.einreichen_planen(doc, self.einst, self.pruefset)
            self.alles_zeichnen()
            self.melden("Fertig. Mit „Viewer öffnen“ ansehen – neue IFC-Modelle werden beim ersten Öffnen einmalig umgewandelt.")
        self.tabs.SelectedIndex = 2
        self.log("Start: %d Paket(e)." % len(aktiv))
        self.auftrag("Einreichen und veröffentlichen", f)

    def _exportieren(self, doc, p):
        v = pakete.ansicht_finden(doc, p) or pakete.ansicht_aufbauen(doc, p, self.plan, self.pruefset)
        tmp = tempfile.mkdtemp(prefix="dbk_ifc_")
        try:
            pfad = aktionen.ifc_aus_ansicht(doc, v, tmp, "export.ifc", self.pruefset,
                                            mit_durchbruechen=p["art"] == pakete.DURCHBRUECHE)
            return aktionen.ifc_veroeffentlichen(doc, self.einst, pfad, p["kuerzel"],
                                                 "%s (%s)" % (doc.Title, v.Name), kopieren=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _viewer(self):
        try:
            viewer_start.oeffnen(self.ordner)
        except Exception as e:
            self.melden("Viewer konnte nicht gestartet werden: %s" % e, fehler=True)


def zeigen(einst):
    fenster = Assistent(einst)
    fenster.show()
    return fenster
