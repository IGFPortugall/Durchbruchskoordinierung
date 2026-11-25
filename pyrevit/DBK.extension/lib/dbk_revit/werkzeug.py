# -*- coding: utf-8 -*-
"""Durchbruchskoordination – ein Werkzeug mit Reitern (Projekt · Durchbrüche · Modell · Einreichen).

Nicht-modal: das Fenster bleibt neben Revit offen. Alles, was die Revit-API braucht,
läuft über ein ExternalEvent (Warteschlange). Der Viewer im Browser ist der Prüf-Manager.
"""
from __future__ import unicode_literals

import io
import json
import os
import shutil
import tempfile
import time
import traceback

from System.Windows import Thickness, Visibility
from System.Windows.Controls import CheckBox, TextBlock, TreeViewItem
from System.Windows.Input import Cursors
from System.Windows.Media import Brushes, SolidColorBrush, ColorConverter
from Autodesk.Revit import UI
from pyrevit import forms

from dbk_core import Ablage
from . import aktionen, ansichten, einstellungen, pakete, sammeln, viewer_start
from .fortschritt import Abgebrochen, Fortschritt
from .sammeln import eid

XAML = os.path.join(os.path.dirname(__file__), "ui", "werkzeug.xaml")
ALLE = "(ohne Vorlage – alle)"
FILTER = ["Alle", "Neu / geändert", "Schon geschickt", "Abgelehnt", "Zurückgehalten"]
KOORD_TEXT = {"offen": "in Prüfung", "blockiert": "abgelehnt", "freigabe": "freigegeben"}


def _pinsel(farbe):
    b = SolidColorBrush(ColorConverter.ConvertFromString(farbe))
    b.Freeze()
    return b


ROT, GRAU, GRUEN, ORANGE = _pinsel("#be0a26"), _pinsel("#71717a"), _pinsel("#3B6D11"), _pinsel("#854F0B")


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
                self.fenster.log("FEHLER %s\n%s" % (titel, traceback.format_exc()))
        self.fenster.beschaeftigt(False)

    def GetName(self):
        return "Durchbruchskoordination"


class _Zeile(object):
    def __init__(self, p, text):
        self.id = p["id"]
        self.text = text


class Werkzeug(forms.WPFWindow):

    def __init__(self, doc):
        forms.WPFWindow.__init__(self, XAML)
        self.einst = einstellungen.laden()
        self.pruefset = {"typen": []}
        self.plan = None
        self.koord = {}            # oid -> Wirkung (offen/blockiert/freigabe) der Koordination
        self.modelle_stand = {}    # Kürzel -> letzter veröffentlichter Stand
        self.baum = {}
        self.alle_ebenen = [e["name"] for e in sammeln.alle_ebenen(doc)]
        self.geschoss_vorschlag = sammeln.geschoss_vorschlag(doc)
        self.ebenen_doc = list(self.alle_ebenen)
        self.vorlagen, self.aktive_vorlage = [], ""
        self.modell_vorlagen = []
        self.modell_auswahl = None
        self._liste_boxen = {}
        self._familien_boxen = []
        self._handler = _Warteschlange(self)
        self._ereignis = UI.ExternalEvent.Create(self._handler)
        self._vorlagen_2d = ansichten.vorlagen(doc, True)
        self._vorlagen_3d = ansichten.vorlagen(doc, False)
        self.doc_titel = doc.Title

        self._verbinden()
        self.projekt_zeichnen()
        if self._bereit():
            self._daten_laden()
            self.einlesen()
        else:
            self.tabs.SelectedItem = self.t_projekt
            self.melden("Willkommen. Bitte zuerst Projektordner, Name, Firma und Rolle festlegen.")
        self._reiter_sichtbarkeit()

    # ================================================================ Grundlagen

    def _verbinden(self):
        self.k_hinweis.Click += lambda s, a: self.naechster_hinweis()
        self.k_revit.Click += lambda s, a: self.in_revit_zeigen()
        self.k_viewer.Click += lambda s, a: self.viewer()
        self.e_viewer.Click += lambda s, a: self.viewer()
        self.k_weiter.Click += lambda s, a: self.weiter()
        self.tabs.SelectionChanged += self._reiter_gewechselt
        self.p_ordner_waehlen.Click += lambda s, a: self._ordner_waehlen()
        self.p_ordner.LostFocus += lambda s, a: self._rollen_laden()
        self.p_speichern.Click += lambda s, a: self.projekt_speichern()
        self.d_familien_ok.Click += lambda s, a: self._familien_uebernehmen()
        self.d_vorlage.SelectionChanged += lambda s, a: self._vorlage_gewechselt()
        self.d_vorlage_speichern.Click += lambda s, a: self._vorlage_speichern(melden=True)
        self.d_vorlage_neu.Click += lambda s, a: self._vorlage_neu()
        self.d_vorlage_weg.Click += lambda s, a: self._vorlage_loeschen()
        self.d_ebene.SelectionChanged += lambda s, a: self._ebene_gewechselt()
        self.d_filter.SelectionChanged += lambda s, a: self.liste_zeichnen()
        self.d_suche.TextChanged += lambda s, a: self.liste_zeichnen()
        self.d_alle.Click += lambda s, a: self._setzen(lambda oid: True)
        self.d_keine.Click += lambda s, a: self._setzen(lambda oid: False)
        self.d_markierung.Click += lambda s, a: self._markierung()
        self.d_zeigen.Click += lambda s, a: self._auswahl_zeigen()
        self.m_liste.SelectionChanged += lambda s, a: self._modell_gewaehlt()
        self.m_neu.Click += lambda s, a: self._modell_neu()
        self.m_weg.Click += lambda s, a: self._modell_weg()
        self.m_speichern.Click += lambda s, a: self._modell_speichern()
        self.m_ansicht.Click += lambda s, a: self._modell_ansicht()
        self.e_los.Click += lambda s, a: self.einreichen()
        self.m_aktualisieren.Click += lambda s, a: self.modell_aktualisieren()
        self.m_format.SelectionChanged += lambda s, a: self._format_info()
        self.p_geschoss_vorschlag.Click += lambda s, a: self._geschosse_setzen(set(self.geschoss_vorschlag))
        self.d_filter.ItemsSource = FILTER
        self.d_filter.SelectedIndex = 0
        self.m_format.ItemsSource = ["FBX – schnell (empfohlen)", "IFC – mit Eigenschaften"]

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

    def log(self, text):
        self.e_log.AppendText("%s  %s\n" % (time.strftime("%H:%M:%S"), text))
        self.e_log.ScrollToEnd()

    def _bereit(self):
        return einstellungen.vollstaendig(self.einst) and bool(self.einst.get("modellkuerzel"))

    def _ersteller(self):
        return (self.einst.get("rolle") or "").upper() in pakete.ERSTELLER or bool(self.einst.get("plant_durchbrueche"))

    def _ordner(self):
        return self.einst["projektordner"], self.einst["firma"]

    # ================================================================ Reiter / Navigation

    def _reiter_sichtbarkeit(self):
        bereit = self._bereit()
        self.t_durch.Visibility = Visibility.Visible if (bereit and self._ersteller()) else Visibility.Collapsed
        self.t_modell.Visibility = Visibility.Visible if bereit else Visibility.Collapsed
        self.t_einreichen.Visibility = Visibility.Visible if (bereit and self._ersteller()) else Visibility.Collapsed
        self.h_projekt.Text = ("✓  Projekt" if bereit else "Projekt")
        self.h_einreichen.Text = "Einreichen" if self._ersteller() else "Veröffentlichen"
        self.e_los.Content = "Einreichen" if self._ersteller() else "Veröffentlichen"
        if bereit:
            self.untertitel.Text = "%s · %s · %s · Modell %s" % (self.einst["name"], self._rollenname(self.einst["rolle"]),
                                                                self.einst["firma"], self.einst["modellkuerzel"])
        else:
            self.untertitel.Text = "Planen · auswählen · einreichen"

    def _sichtbare_reiter(self):
        return [t for t in (self.t_projekt, self.t_durch, self.t_modell, self.t_einreichen)
                if t.Visibility == Visibility.Visible]

    def weiter(self):
        reiter = self._sichtbare_reiter()
        i = reiter.index(self.tabs.SelectedItem) if self.tabs.SelectedItem in reiter else 0
        if self.tabs.SelectedItem == self.t_projekt and not self._bereit():
            self.projekt_speichern()
            return
        if i + 1 < len(reiter):
            self.tabs.SelectedItem = reiter[i + 1]

    def _reiter_gewechselt(self, sender, args):
        if args.OriginalSource != self.tabs:
            return
        t = self.tabs.SelectedItem
        letzter = self._sichtbare_reiter()[-1] if self._sichtbare_reiter() else None
        self.k_weiter.Visibility = Visibility.Collapsed if t == letzter else Visibility.Visible
        if t == self.t_einreichen:
            self.zusammenfassung_zeichnen()

    def naechster_hinweis(self):
        if not self._bereit():
            self.tabs.SelectedItem = self.t_projekt
            self.melden("Hinweis: Projekt noch nicht vollständig eingerichtet.", fehler=True)
            return
        if self._ersteller() and self.plan is not None:
            abgelehnt = [o for o in self.plan.objekte if self.koord.get(o) == "blockiert"]
            if abgelehnt:
                self.tabs.SelectedItem = self.t_durch
                self.d_filter.SelectedIndex = 3
                self.melden("Hinweis: %d abgelehnte Durchbrüche – bitte nacharbeiten oder im Viewer klären." % len(abgelehnt), fehler=True)
                return
            if self._gewaehlt():
                self.tabs.SelectedItem = self.t_einreichen
                self.melden("Hinweis: %d Durchbrüche sind ausgewählt und noch nicht eingereicht." % len(self._gewaehlt()))
                return
        if not self.modell_vorlagen:
            self.tabs.SelectedItem = self.t_modell
            self.melden("Hinweis: noch keine Modell-Vorlage – mit „+ Vorlage“ anlegen.")
            return
        self.melden("Keine offenen Hinweise.")

    # ================================================================ Reiter 1: Projekt

    def projekt_zeichnen(self):
        e = self.einst
        self.p_ordner.Text = e.get("projektordner", "")
        self.p_name.Text = e.get("name", "")
        self.p_firma.Text = e.get("firma", "")
        self.p_kuerzel.Text = e.get("modellkuerzel", "") or "HLS"
        self.p_plant.IsChecked = bool(e.get("plant_durchbrueche"))
        leer = "(keine Vorlage)"
        self.p_vorlage_2d.ItemsSource = [leer] + self._vorlagen_2d
        self.p_vorlage_3d.ItemsSource = [leer] + self._vorlagen_3d
        self.p_vorlage_2d.SelectedItem = e.get("vorlage_2d") or leer
        self.p_vorlage_3d.SelectedItem = e.get("vorlage_3d") or leer
        self._rollen_laden(e.get("rolle"))
        geschosse = None
        if self._bereit():
            geschosse = sammeln.pruefset_laden(e["projektordner"], e["firma"]).get("geschosse")
        self._geschosse_setzen(set(geschosse) if geschosse else set(self.geschoss_vorschlag))

    def _geschosse_setzen(self, auswahl):
        self.p_geschosse.Children.Clear()
        for name in self.alle_ebenen:
            b = CheckBox()
            b.Content = name
            b.IsChecked = name in auswahl
            b.Margin = Thickness(0, 1, 0, 1)
            self.p_geschosse.Children.Add(b)

    def _geschosse_gewaehlt(self):
        return [b.Content for b in self.p_geschosse.Children if b.IsChecked]

    def _ordner_waehlen(self):
        pfad = forms.pick_folder(title="Projektordner der Durchbruchskoordination")
        if pfad:
            self.p_ordner.Text = pfad
            self._rollen_laden()

    def _rollen_laden(self, auswahl=None):
        self._rollen = []
        ordner = (self.p_ordner.Text or "").strip()
        pfad = os.path.join(ordner, "projekt.json")
        if os.path.isfile(pfad):
            try:
                with io.open(pfad, "r", encoding="utf-8-sig") as f:
                    self._rollen = json.load(f).get("rollen", [])
                a = Ablage(ordner)
                a.lade_neue()
                self.p_firma.ItemsSource = sorted(set(ev["firma"] for ev in a.alle()))
            except (IOError, OSError, ValueError):
                pass
        else:
            self._rollen = list(einstellungen.PROJEKT_VORLAGE["rollen"])
        alt = auswahl or (self.p_rolle.SelectedItem.split("  ")[0] if self.p_rolle.SelectedItem else None)
        self.p_rolle.ItemsSource = ["%s  (%s)" % (r["id"], r["name"]) for r in self._rollen]
        for i, r in enumerate(self._rollen):
            if r["id"] == alt:
                self.p_rolle.SelectedIndex = i

    def _rollenname(self, rid):
        for r in getattr(self, "_rollen", []) or []:
            if r["id"] == rid:
                return r["name"]
        return rid

    def projekt_speichern(self):
        ordner = (self.p_ordner.Text or "").strip()
        if not ordner or not os.path.isdir(ordner):
            self.melden("Bitte einen vorhandenen Projektordner wählen.", fehler=True)
            return
        if not os.path.isfile(os.path.join(ordner, "projekt.json")):
            if not forms.alert("In diesem Ordner gibt es noch kein Projekt:\n%s\n\nHier ein neues Projekt anlegen?\n"
                               "Wenn andere es schon angelegt haben, bitte stattdessen deren Ordner wählen." % ordner,
                               title="Neues Projekt", yes=True, no=True):
                return
            name = forms.ask_for_string(default=os.path.basename(ordner), prompt="Projektname:", title="Neues Projekt")
            if not name:
                return
            einstellungen.projekt_anlegen(ordner, name)
            self._rollen_laden()
        e = dict(self.einst)
        e["projektordner"] = ordner
        e["name"] = (self.p_name.Text or "").strip()
        e["firma"] = (self.p_firma.Text or "").strip()
        e["rolle"] = self._rollen[self.p_rolle.SelectedIndex]["id"] if self.p_rolle.SelectedIndex >= 0 else ""
        e["modellkuerzel"] = einstellungen.kuerzel_bereinigen(self.p_kuerzel.Text)
        e["plant_durchbrueche"] = bool(self.p_plant.IsChecked)
        e["vorlage_2d"] = "" if self.p_vorlage_2d.SelectedIndex <= 0 else self.p_vorlage_2d.SelectedItem
        e["vorlage_3d"] = "" if self.p_vorlage_3d.SelectedIndex <= 0 else self.p_vorlage_3d.SelectedItem
        self.p_kuerzel.Text = e["modellkuerzel"]
        if not (e["name"] and e["firma"] and e["rolle"] and e["modellkuerzel"]):
            self.melden("Bitte Name, Firma, Rolle und Kürzel angeben.", fehler=True)
            return
        geschosse = self._geschosse_gewaehlt()
        if not geschosse:
            self.melden("Bitte mindestens eine Ebene als Geschoss anhaken.", fehler=True)
            return
        einstellungen.speichern(e)
        self.einst = e
        ps = sammeln.pruefset_laden(e["projektordner"], e["firma"])
        ps["geschosse"] = geschosse
        sammeln.pruefset_speichern(e["projektordner"], e["firma"], ps)
        self._reiter_sichtbarkeit()
        self._daten_laden()
        self.einlesen()
        self.tabs.SelectedItem = self.t_durch if self._ersteller() else self.t_modell
        self.melden("Gespeichert.")

    # ================================================================ Daten

    def _daten_laden(self):
        ordner, firma = self._ordner()
        self.pruefset = sammeln.pruefset_laden(ordner, firma)
        gs = set(self.pruefset.get("geschosse") or [])
        self.ebenen_doc = [n for n in self.alle_ebenen if n in gs] or list(self.alle_ebenen)
        self.vorlagen, self.aktive_vorlage = pakete.vorlagen_laden(ordner, firma)
        self.modell_vorlagen = [p for p in pakete.laden(ordner, firma) if p["art"] == pakete.TGA]
        if not self.modell_vorlagen:
            gewerke = [g[0] for g in pakete.gewerke_fuer(self.einst["rolle"])]
            name = "TGA ohne Durchbrüche" if self._ersteller() else "%s gesamt" % self._rollenname(self.einst["rolle"])
            self.modell_vorlagen = [pakete.neu(pakete.TGA, name, self.einst["modellkuerzel"], gewerke)]
            self._modelle_sichern()

    def _modelle_sichern(self):
        ordner, firma = self._ordner()
        alle = [p for p in pakete.laden(ordner, firma) if p["art"] != pakete.TGA] + self.modell_vorlagen
        pakete.speichern(ordner, firma, alle)

    def einlesen(self):
        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            ordner, firma = self._ordner()
            self.pruefset = sammeln.pruefset_laden(ordner, firma)
            self.baum = sammeln.baum(doc) if self._ersteller() else {}
            self.plan = aktionen.einreichen_planen(doc, self.einst, self.pruefset)
            ablage, z = aktionen.zustand_laden(ordner)
            self.koord = dict((oid, z.gesamtstatus(oid)["wirkung"]) for oid in z.objekte)
            self.modelle_stand = dict((k, v["aktuell"]) for k, v in z.modelle.items())
            self.alles_zeichnen()
            if self._ersteller():
                self.melden("%d Durchbrüche gelesen: %d neu, %d verschoben/geändert, %d unverändert, %d abgelehnt."
                            % (len(self.plan.objekte), len(self.plan.neu), len(self.plan.geometrie), self.plan.unveraendert,
                               len([o for o in self.plan.objekte if self.koord.get(o) == "blockiert"])))
            else:
                self.melden("Bereit.")
        self.auftrag("Modell und Projektordner einlesen", f)

    def alles_zeichnen(self):
        if self._ersteller():
            self.familien_zeichnen()
            self.vorlagen_zeichnen()
        self.modelle_zeichnen()
        self.zusammenfassung_zeichnen()

    # ================================================================ Reiter 2: Durchbrüche

    def familien_zeichnen(self):
        self.d_familien.Items.Clear()
        self._familien_boxen = []
        gewaehlt = set((t["kategorie"], t["familie"], t["typ"]) for t in self.pruefset.get("typen", []))
        for kat in sorted(self.baum):
            k_item = TreeViewItem()
            k_item.Header = kat
            for fam in sorted(self.baum[kat]):
                f_item = TreeViewItem()
                f_box = CheckBox()
                f_box.Content = fam
                f_box.Tag = []
                f_item.Header = f_box
                for typ in sorted(self.baum[kat][fam]):
                    b = CheckBox()
                    b.Content = "%s  (%d)" % (typ, self.baum[kat][fam][typ])
                    b.IsChecked = (kat, fam, typ) in gewaehlt
                    t_item = TreeViewItem()
                    t_item.Header = b
                    f_item.Items.Add(t_item)
                    f_box.Tag.append(b)
                    self._familien_boxen.append((b, kat, fam, typ))
                f_box.IsChecked = all(b.IsChecked for b in f_box.Tag) if f_box.Tag else False

                def umschalten(s, a, box=f_box):
                    for kind in box.Tag:
                        kind.IsChecked = box.IsChecked
                f_box.Click += umschalten
                if any((kat, fam, t) in gewaehlt for t in self.baum[kat][fam]):
                    k_item.IsExpanded = True
                k_item.Items.Add(f_item)
            self.d_familien.Items.Add(k_item)

    def _familien_uebernehmen(self):
        ordner, firma = self._ordner()
        typen = [{"kategorie": k, "familie": f, "typ": t} for b, k, f, t in self._familien_boxen if b.IsChecked]
        ps = sammeln.pruefset_laden(ordner, firma)
        ps["typen"] = typen
        ps["modell"] = self.einst["modellkuerzel"]
        sammeln.pruefset_speichern(ordner, firma, ps)
        self.einlesen()

    # ---------------------------------------------------------------- Vorlagen

    def _vorlage(self):
        return next((v for v in self.vorlagen if v["id"] == self.aktive_vorlage), None)

    def vorlagen_zeichnen(self):
        self._vorlage_sperre = True
        namen = [ALLE] + [v["name"] for v in self.vorlagen]
        self.d_vorlage.ItemsSource = namen
        v = self._vorlage()
        self.d_vorlage.SelectedItem = v["name"] if v else ALLE
        ebenen = []
        if self.plan is not None:
            ebenen = sorted(set(d.get("ebene") for d in self.plan.objekte.values()),
                            key=lambda n: self.ebenen_doc.index(n) if n in self.ebenen_doc else 999)
        self.d_ebene.ItemsSource = ["Alle Ebenen"] + ebenen
        auswahl = (v.get("ebenen") or [None])[0] if v else None
        self.d_ebene.SelectedItem = auswahl if auswahl in ebenen else "Alle Ebenen"
        self.d_vorlage_speichern.IsEnabled = self.d_vorlage_weg.IsEnabled = v is not None
        self._vorlage_sperre = False
        self.liste_zeichnen()

    def _vorlage_gewechselt(self):
        if getattr(self, "_vorlage_sperre", False):
            return
        name = self.d_vorlage.SelectedItem
        v = next((x for x in self.vorlagen if x["name"] == name), None)
        self.aktive_vorlage = v["id"] if v else ""
        pakete.vorlagen_speichern(self.einst["projektordner"], self.einst["firma"], self.vorlagen, self.aktive_vorlage)
        self.vorlagen_zeichnen()

    def _vorlage_neu(self):
        name = forms.ask_for_string(default="EG Rohbau", prompt="Name der Auswahlvorlage:", title="Neue Auswahlvorlage")
        if not name:
            return
        if any(v["name"] == name for v in self.vorlagen):
            self.melden("Eine Vorlage mit diesem Namen gibt es schon.", fehler=True)
            return
        v = pakete.neue_vorlage(name)
        if self.d_ebene.SelectedIndex > 0:
            v["ebenen"] = [self.d_ebene.SelectedItem]
        self.vorlagen.append(v)
        self.aktive_vorlage = v["id"]
        self._vorlage_speichern(melden=False)
        self.vorlagen_zeichnen()
        self.melden("Vorlage „%s“ angelegt." % name)

    def _vorlage_loeschen(self):
        v = self._vorlage()
        if v and forms.alert("Auswahlvorlage „%s“ löschen?" % v["name"], yes=True, no=True):
            self.vorlagen.remove(v)
            self.aktive_vorlage = ""
            pakete.vorlagen_speichern(self.einst["projektordner"], self.einst["firma"], self.vorlagen, "")
            self.vorlagen_zeichnen()

    def _vorlage_speichern(self, melden=True):
        v = self._vorlage()
        if v is None:
            return
        v["ebenen"] = [self.d_ebene.SelectedItem] if self.d_ebene.SelectedIndex > 0 else []
        if self.plan is not None:
            v["bekannt"] = sorted(pakete.in_vorlage(v, self.plan))
        pakete.vorlagen_speichern(self.einst["projektordner"], self.einst["firma"], self.vorlagen, self.aktive_vorlage)
        if melden:
            self.melden("Vorlage „%s“ gespeichert." % v["name"])
            self.liste_zeichnen()

    def _ebene_gewechselt(self):
        if getattr(self, "_vorlage_sperre", False):
            return
        v = self._vorlage()
        if v is not None:
            v["ebenen"] = [self.d_ebene.SelectedItem] if self.d_ebene.SelectedIndex > 0 else []
            pakete.vorlagen_speichern(self.einst["projektordner"], self.einst["firma"], self.vorlagen, self.aktive_vorlage)
        self.liste_zeichnen()

    # ---------------------------------------------------------------- Exemplarliste

    def _aus(self):
        v = self._vorlage()
        return set(v.get("aus") or []) if v else set(self.pruefset.get("ausgeschlossen") or [])

    def _aus_setzen(self, aus):
        v = self._vorlage()
        ordner, firma = self._ordner()
        if v is not None:
            v["aus"] = sorted(aus)
            pakete.vorlagen_speichern(ordner, firma, self.vorlagen, self.aktive_vorlage)
        else:
            ps = sammeln.pruefset_laden(ordner, firma)
            ps["ausgeschlossen"] = sorted(aus)
            sammeln.pruefset_speichern(ordner, firma, ps)
            self.pruefset["ausgeschlossen"] = ps["ausgeschlossen"]

    def _kandidaten(self):
        """Objekt-IDs der aktuellen Vorlage/Ebene."""
        if self.plan is None:
            return []
        ebene = self.d_ebene.SelectedItem if self.d_ebene.SelectedIndex > 0 else None
        oids = pakete.in_vorlage(self._vorlage(), self.plan)
        return [o for o in oids if not ebene or self.plan.objekte[o].get("ebene") == ebene]

    def _waehlbar(self, oid):
        return self.plan.zustand[oid] in (aktionen.NEU, aktionen.GEOMETRIE, aktionen.DATEN)

    def _gewaehlt(self):
        if self.plan is None:
            return []
        aus = self._aus()
        return [o for o in self._kandidaten() if self._waehlbar(o) and o not in aus]

    def _zeilentext(self, oid, neu_dazu):
        d = self.plan.objekte[oid]
        z = self.plan.zustand[oid]
        k = self.koord.get(oid)
        if z == aktionen.UNVERAENDERT:
            zustand = "geschickt · %s" % KOORD_TEXT.get(k, "in Prüfung")
        elif z == aktionen.FREMD:
            zustand = "gehört anderer Firma"
        elif z == aktionen.NEU:
            zustand = "neu" + (" · neu hinzugekommen" if neu_dazu else "")
        elif k == "blockiert":
            zustand = "abgelehnt → geändert"
        else:
            zustand = aktionen.ZUSTAND_TEXT[z]
        w = d.get("wirt") or {}
        wirt = {"Wände": "Wand", "Geschossdecken": "Decke"}.get(w.get("kategorie"), w.get("kategorie") or "")
        if w.get("tragend"):
            wirt += " tragend"
        return "%s  ·  %s %s  ·  %s  ·  %s" % (d.get("nummer"), d.get("typ"), d.get("groesse"), wirt, zustand)

    def liste_zeichnen(self):
        self.d_liste.Items.Clear()
        self._liste_boxen = {}
        if self.plan is None:
            return
        v = self._vorlage()
        bekannt = set(v.get("bekannt") or []) if v else None
        aus = self._aus()
        filt = self.d_filter.SelectedIndex
        such = (self.d_suche.Text or "").strip().lower()
        gruppen = {}
        neu_dazu_anzahl = 0
        for oid in self._kandidaten():
            z = self.plan.zustand[oid]
            k = self.koord.get(oid)
            neu_dazu = bekannt is not None and bool(bekannt) and oid not in bekannt
            if neu_dazu and self._waehlbar(oid) and oid not in aus:
                neu_dazu_anzahl += 1
            if filt == 1 and not self._waehlbar(oid):
                continue
            if filt == 2 and z != aktionen.UNVERAENDERT:
                continue
            if filt == 3 and k != "blockiert":
                continue
            if filt == 4 and not (oid in aus and self._waehlbar(oid)):
                continue
            text = self._zeilentext(oid, neu_dazu)
            if such and such not in (text + " " + (self.plan.objekte[oid].get("familie") or "")).lower():
                continue
            gruppen.setdefault(self.plan.objekte[oid].get("ebene"), []).append((oid, text, neu_dazu))
        for ebene in sorted(gruppen, key=lambda n: self.ebenen_doc.index(n) if n in self.ebenen_doc else 999):
            knoten = TreeViewItem()
            knoten.Header = "%s  (%d)" % (ebene, len(gruppen[ebene]))
            knoten.IsExpanded = len(gruppen) <= 3 or filt in (1, 3)
            for oid, text, neu_dazu in sorted(gruppen[ebene], key=lambda x: self.plan.objekte[x[0]].get("nummer", "")):
                b = CheckBox()
                b.Content = text
                b.Tag = oid
                waehlbar = self._waehlbar(oid)
                b.IsEnabled = waehlbar
                b.IsChecked = (oid not in aus) if waehlbar else (self.plan.zustand[oid] == aktionen.UNVERAENDERT)
                if self.koord.get(oid) == "blockiert":
                    b.Foreground = ROT
                elif neu_dazu or self.plan.zustand[oid] == aktionen.NEU:
                    b.Foreground = ORANGE if neu_dazu else b.Foreground
                elif self.koord.get(oid) == "freigabe":
                    b.Foreground = GRUEN
                b.Click += lambda s, a: self._haken_geaendert(s)
                item = TreeViewItem()
                item.Header = b
                knoten.Items.Add(item)
                self._liste_boxen[oid] = b
            self.d_liste.Items.Add(knoten)
        self.d_info.Text = ("%d neu hinzugekommen – angehakt" % neu_dazu_anzahl) if neu_dazu_anzahl else ""
        self._summe()

    def _haken_geaendert(self, box):
        aus = self._aus()
        if box.IsChecked:
            aus.discard(box.Tag)
        else:
            aus.add(box.Tag)
        self._aus_setzen(aus)
        self._summe()

    def _setzen(self, regel):
        aus = self._aus()
        for oid, b in self._liste_boxen.items():
            if not b.IsEnabled:
                continue
            an = bool(regel(oid))
            b.IsChecked = an
            if an:
                aus.discard(oid)
            else:
                aus.add(oid)
        self._aus_setzen(aus)
        self._summe()

    def _summe(self):
        n = len(self._gewaehlt())
        self.d_summe.Text = "%d gehen in die nächste Runde" % n
        self.h_durch.Text = "Durchbrüche  (%d)" % n if n else "Durchbrüche"

    def _markierung(self):
        def f(uiapp):
            ids = set(eid(i) for i in uiapp.ActiveUIDocument.Selection.GetElementIds())
            if not ids:
                self.melden("In Revit ist nichts markiert.", fehler=True)
                return
            self._setzen(lambda oid: eid(self.plan.element_ids[oid]) in ids)
            self.melden("Revit-Markierung übernommen.")
        self.auftrag("Revit-Markierung übernehmen", f)

    def _auswahl_zeigen(self):
        if self.plan is None:
            return
        alle = [self.plan.element_ids[o] for o in self._kandidaten()]
        gewaehlt = [self.plan.element_ids[o] for o in self._gewaehlt()]

        def f(uiapp):
            ansichten.kontrollansicht(uiapp.ActiveUIDocument, self.einst, alle, gewaehlt)
            self.melden("Kontrollansicht: orange = geht in die nächste Runde, grau = schon geschickt oder zurückgehalten.")
        self.auftrag("Auswahl in Revit zeigen", f)

    # ================================================================ Reiter 3: Modell

    def modelle_zeichnen(self):
        zeilen = []
        for p in self.modell_vorlagen:
            stand = self.modelle_stand.get(p["kuerzel"])
            zeilen.append(_Zeile(p, "%s %s   →  %s   ·  %s  ·  %s" % (
                "☑" if p.get("aktiv", True) else "☐", p["name"], p["kuerzel"], (p.get("format") or aktionen.FBX).upper(),
                "zuletzt %s" % stand["stand"] if stand else "noch nie veröffentlicht")))
        aktiv = [p for p in self.modell_vorlagen if p.get("aktiv", True)]
        self.m_hinweis.Text = ("„Modell aktualisieren“ stellt %d angehakte Vorlage(n) in den Viewer. Unabhängig vom Einreichen "
                               "der Durchbrüche – nur nötig, wenn sich das Modell geändert hat." % len(aktiv))
        self._modell_sperre = True
        self.m_liste.ItemsSource = zeilen
        for z in zeilen:
            if z.id == self.modell_auswahl:
                self.m_liste.SelectedItem = z
        if self.m_liste.SelectedItem is None and zeilen:
            self.m_liste.SelectedIndex = 0
        self._modell_sperre = False
        self._modell_gewaehlt()

    def _modell(self):
        return next((p for p in self.modell_vorlagen if p["id"] == self.modell_auswahl), None)

    def _format_info(self):
        self.m_format_info.Text = aktionen.FORMAT_TEXT[aktionen.IFC if self.m_format.SelectedIndex == 1 else aktionen.FBX]

    def _modell_gewaehlt(self):
        if getattr(self, "_modell_sperre", False):
            return
        z = self.m_liste.SelectedItem
        self.modell_auswahl = z.id if z is not None else None
        p = self._modell()
        self.m_editor.IsEnabled = p is not None
        self.m_gewerke.Children.Clear()
        self.m_ebenen.Children.Clear()
        if p is None:
            return
        self.m_aktiv.IsChecked = bool(p.get("aktiv", True))
        self.m_name.Text = p["name"]
        self.m_kuerzel.Text = p["kuerzel"]
        self.m_format.SelectedIndex = 1 if p.get("format") == aktionen.IFC else 0
        self._format_info()
        stand = self.modelle_stand.get(p["kuerzel"])
        self.m_stand.Text = ("Im Viewer: Stand %s (%s)." % (stand["stand"], stand.get("firma", "")) if stand
                             else "Noch nicht im Viewer.")
        for name, _ in pakete.gewerke_fuer(self.einst["rolle"]):
            b = CheckBox()
            b.Content = name
            b.IsChecked = name in (p.get("gewerke") or [])
            b.Margin = Thickness(0, 1, 0, 1)
            self.m_gewerke.Children.Add(b)
        for name in self.ebenen_doc:
            b = CheckBox()
            b.Content = name
            b.IsChecked = name in (p.get("ebenen") or [])
            b.Margin = Thickness(0, 1, 0, 1)
            self.m_ebenen.Children.Add(b)

    def _modell_speichern(self):
        p = self._modell()
        if p is None:
            return None
        name = (self.m_name.Text or "").strip()
        kuerzel = einstellungen.kuerzel_bereinigen(self.m_kuerzel.Text)
        if not name or not kuerzel:
            self.melden("Bitte Name und Kürzel angeben.", fehler=True)
            return None
        if any(q is not p and (q["name"] == name or q["kuerzel"] == kuerzel) for q in self.modell_vorlagen):
            self.melden("Name oder Kürzel gibt es schon.", fehler=True)
            return None
        p.update({"name": name, "kuerzel": kuerzel, "aktiv": bool(self.m_aktiv.IsChecked),
                  "format": aktionen.IFC if self.m_format.SelectedIndex == 1 else aktionen.FBX,
                  "gewerke": [b.Content for b in self.m_gewerke.Children if b.IsChecked],
                  "ebenen": [b.Content for b in self.m_ebenen.Children if b.IsChecked]})
        self._modelle_sichern()
        self.modelle_zeichnen()
        self.melden("Modell-Vorlage „%s“ gespeichert." % name)
        return p

    def _modell_neu(self):
        n = len(self.modell_vorlagen) + 1
        p = pakete.neu(pakete.TGA, "Modell %d" % n, "%s-%d" % (self.einst["modellkuerzel"], n),
                       [g[0] for g in pakete.gewerke_fuer(self.einst["rolle"])])
        self.modell_vorlagen.append(p)
        self.modell_auswahl = p["id"]
        self._modelle_sichern()
        self.modelle_zeichnen()
        self.m_name.Focus()
        self.m_name.SelectAll()

    def _modell_weg(self):
        p = self._modell()
        if p and forms.alert("Modell-Vorlage „%s“ entfernen? Die Revit-Ansicht bleibt bestehen." % p["name"], yes=True, no=True):
            self.modell_vorlagen.remove(p)
            self.modell_auswahl = None
            self._modelle_sichern()
            self.modelle_zeichnen()

    def _modell_ansicht(self):
        p = self._modell_speichern()
        if p is None or self.plan is None:
            return

        def f(uiapp):
            uidoc = uiapp.ActiveUIDocument
            v = pakete.ansicht_aufbauen(uidoc.Document, p, self.plan, self.pruefset)
            uidoc.ActiveView = v
            kats = pakete.tga_zaehlen(uidoc.Document, p, set(eid(i) for i in self.plan.element_ids.values()))
            n = sum(kats.values())
            self.melden("„%s“: %d Bauteile sichtbar (%s). Exportiert wird genau das – in Revit nach Bedarf ausblenden, "
                        "filtern oder Schnittbox setzen." % (v.Name, n, ", ".join("%s %d" % kv for kv in
                                                                                   sorted(kats.items(), key=lambda kv: -kv[1])[:4])))
        self.auftrag("Exportansicht „%s“" % p["name"], f)

    # ================================================================ Reiter 4: Einreichen

    def zusammenfassung_zeichnen(self):
        if not self._bereit():
            return
        n = len(self._gewaehlt()) if self._ersteller() else 0
        v = self._vorlage()
        zeilen = ["•  Durchbrüche: %d gehen in die Prüfung%s" % (n, " (Vorlage „%s“)" % v["name"] if v else "")]
        if n == 0:
            zeilen.append("   Nichts Neues oder Geändertes ausgewählt.")
        zeilen.append("•  Modelle werden hier nicht mitgeschickt – dafür im Reiter „Modell“ auf „Modell aktualisieren“.")
        self.e_zusammenfassung.Text = "\n".join(zeilen)
        self.e_runde_box.Visibility = Visibility.Visible if n else Visibility.Collapsed
        if not (self.e_runde.Text or "").strip():
            self.e_runde.Text = "Prüfrunde %s" % time.strftime("%d.%m.%Y")
        m = len(self.plan.entfallen) if (self.plan is not None and self._ersteller()) else 0
        self.e_entfallen.Content = "Im Modell gelöschte Durchbrüche aus der Koordination entfernen (%d)" % m
        self.e_entfallen.Visibility = Visibility.Visible if m else Visibility.Collapsed
        self.e_entfallen.IsChecked = m > 0

    def einreichen(self):
        """Nur Durchbrüche – dauert Sekunden. Modelle laufen getrennt über „Modell aktualisieren“."""
        auswahl = set(self._gewaehlt())
        entfallen = bool(self.e_entfallen.IsChecked) and self.e_entfallen.Visibility == Visibility.Visible
        if not auswahl and not entfallen:
            self.melden("Nichts zum Einreichen ausgewählt.", fehler=True)
            return
        runde = (self.e_runde.Text or "").strip()
        if auswahl and not runde:
            self.melden("Bitte einen Namen für die Prüfrunde angeben.", fehler=True)
            return

        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            with Fortschritt("Durchbrüche einreichen", ["Durchbrüche lesen", "In den Projektordner schreiben",
                                                         "Auswahlvorlage merken"]) as fs:
                fs.schritt(0, "Lage, Größe und Bauteil je Durchbruch …")
                plan = aktionen.einreichen_planen(doc, self.einst, self.pruefset,
                                                  fortschritt=lambda i, n: fs.menge(i, n, "Durchbrüche"))
                fs.schritt(1, "%d Durchbrüche, Prüfrunde „%s“" % (len(auswahl), runde))
                r = aktionen.einreichen_ausfuehren(self.einst, plan, rundenname=runde,
                                                   auswahl=set(o for o in auswahl if o in plan.objekte), entfallen=entfallen)
                fs.schritt(2)
                v = self._vorlage()
                if v is not None:
                    v["bekannt"] = sorted(set(v.get("bekannt") or []) | set(pakete.in_vorlage(v, plan)))
                    pakete.vorlagen_speichern(self.einst["projektordner"], self.einst["firma"], self.vorlagen, self.aktive_vorlage)
                fs.fertig()
                fs.detail("%d zur Prüfung, %d Datenabgleich, %d entfernt." % (r["eingereicht"], r["geaendert"], r["geloescht"]))
            self.log("Durchbrüche: %d zur Prüfung, %d Datenabgleich, %d entfernt (Runde „%s“)."
                     % (r["eingereicht"], r["geaendert"], r["geloescht"], runde))
        self.auftrag("Einreichen", f)
        self.einlesen()

    def modell_aktualisieren(self):
        """Angehakte Modell-Vorlagen exportieren (FBX oder IFC) und in den Viewer stellen – nur wenn geändert."""
        if self._modell() is not None and self._modell_speichern() is None:
            return
        aktiv = [p for p in self.modell_vorlagen if p.get("aktiv", True)]
        if not aktiv:
            self.melden("Keine Modell-Vorlage angehakt („Beim Einreichen mitschicken“).", fehler=True)
            return
        erzwingen = bool(self.m_erzwingen.IsChecked)

        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            version = aktionen.modell_version(doc)
            schritte = []
            for p in aktiv:
                fmt = (p.get("format") or aktionen.FBX).upper()
                schritte += ["%s: Ansicht vorbereiten" % p["name"], "%s: %s-Export durch Revit" % (p["name"], fmt),
                             "%s: in den Projektordner kopieren" % p["name"]]
            with Fortschritt("Modell aktualisieren", schritte) as fs:
                for i, p in enumerate(aktiv):
                    s0 = 3 * i
                    konfig = json.dumps([p.get("format"), sorted(p.get("gewerke") or []), sorted(p.get("ebenen") or [])])
                    unveraendert = (version and p.get("letzte_version") == version and p.get("letzte_konfig") == konfig
                                    and not doc.IsModified and p["kuerzel"] in self.modelle_stand)
                    if unveraendert and not erzwingen:
                        for k in range(3):
                            fs.ueberspringen(s0 + k, "unverändert seit %s" % self.modelle_stand[p["kuerzel"]]["stand"])
                        self.log("„%s“: unverändert – übersprungen." % p["name"])
                        continue
                    fs.schritt(s0, "Exportansicht „%s“" % pakete.ansicht_name(p))
                    plan = self.plan or aktionen.einreichen_planen(doc, self.einst, self.pruefset)
                    v = pakete.ansicht_finden(doc, p) or pakete.ansicht_aufbauen(doc, p, plan, self.pruefset)
                    fmt = p.get("format") or aktionen.FBX
                    zusatz = None
                    if fmt == aktionen.FBX:
                        fs.detail("Bauteil-Infos sammeln …")
                        zusatz = aktionen.bauteil_infos(doc, v, self.pruefset,
                                                        fortschritt=lambda a, b: fs.menge(a, b, "Bauteile"))
                    fs.schritt(s0 + 1, "Revit exportiert – das kann einige Minuten dauern. Revit zeigt unten seinen "
                                       "eigenen Fortschritt und reagiert so lange nicht.")
                    tmp = tempfile.mkdtemp(prefix="dbk_export_")
                    try:
                        start = time.time()
                        if fmt == aktionen.FBX:
                            pfad = aktionen.fbx_aus_ansicht(doc, v, tmp, "export.fbx", self.pruefset)
                        else:
                            pfad = aktionen.ifc_aus_ansicht(doc, v, tmp, "export.ifc", self.pruefset)
                        dauer = time.time() - start
                        fs.schritt(s0 + 2, "%.0f MB nach %d:%02d min exportiert" % (os.path.getsize(pfad) / 1e6,
                                                                                  int(dauer) // 60, int(dauer) % 60))
                        d = aktionen.datei_veroeffentlichen(doc, self.einst, pfad, p["kuerzel"], "%s (%s)" % (doc.Title, v.Name),
                                                            fmt, geschosse=self.pruefset.get("geschosse"), zusatz=zusatz,
                                                            version=version, fortschritt=lambda a, b: fs.menge(a, b, "MB"))
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
                    p["letzte_version"], p["letzte_konfig"] = version, konfig
                    self._modelle_sichern()
                    self.log("„%s“ als %s veröffentlicht (%s MB, Export %d:%02d min)."
                             % (p["name"], fmt.upper(), d["groesse_mb"], int(dauer) // 60, int(dauer) % 60))
                fs.fertig()
        self.auftrag("Modell aktualisieren", f)
        self.einlesen()

    # ================================================================ Werkzeugleiste

    def in_revit_zeigen(self):
        if self.tabs.SelectedItem == self.t_modell:
            self._modell_ansicht()
            return
        item = self.d_liste.SelectedItem
        oid = item.Header.Tag if (item is not None and isinstance(item.Header, CheckBox)) else None
        if oid is None or self.plan is None:
            self.melden("Bitte im Reiter „Durchbrüche“ eine Zeile markieren.", fehler=True)
            return
        objekt = dict(self.plan.objekte[oid])

        def f(uiapp):
            ansichten.zeige_3d(uiapp, objekt, self.einst)
        self.auftrag("In Revit zeigen", f)

    def viewer(self):
        if not self._bereit():
            self.melden("Bitte zuerst das Projekt einrichten.", fehler=True)
            return
        try:
            viewer_start.oeffnen(self.einst["projektordner"])
        except Exception as e:
            self.melden("Viewer konnte nicht gestartet werden: %s" % e, fehler=True)


def zeigen(doc):
    fenster = Werkzeug(doc)
    fenster.show()
    return fenster
