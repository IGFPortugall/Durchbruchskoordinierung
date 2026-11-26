# -*- coding: utf-8 -*-
"""Durchbruchskoordination – ein Werkzeug mit Reitern (Projekt · Durchbrüche · Einreichen).

Ein Stand ist Name + 3D-Ansicht: was in der Ansicht von den Koordinations-Familien sichtbar ist,
gehört dazu. Einreichen schickt den ganzen Stand als Momentaufnahme (neu / geändert /
unverändert); was fehlt, fällt heraus.

Reiter: Projekt · Ansichten (3D-Modelle und 2D-Pläne für den Viewer, modelle.py) · Durchbrüche · Einreichen.

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

import System
from System.Windows import Thickness, Visibility
from System.Windows.Controls import CheckBox, TextBlock, TreeViewItem
from System.Windows.Input import Cursors
from System.Windows.Media import Brushes, SolidColorBrush, ColorConverter
from Autodesk.Revit import DB, UI
from pyrevit import forms

from dbk_core import Ablage
from . import aktionen, ansichten, einstellungen, modelle, pakete, sammeln, staende, viewer_start
from .fortschritt import Abgebrochen, Fortschritt
from .sammeln import eid

XAML = os.path.join(os.path.dirname(__file__), "ui", "werkzeug.xaml")
FILTER = ["Alle", "Neu / geändert", "Unverändert", "Entfallen", "Andere Firma"]
FILTER_ARTEN = [None, ("neu", "geaendert", "daten"), ("unveraendert",), ("entfaellt",), ("fremd",)]
ART_TEXT = {"neu": "neu", "geaendert": "geändert", "daten": "Daten geändert", "unveraendert": "unverändert",
            "entfaellt": "entfällt", "fremd": "gehört anderer Firma"}
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
                aktiv = uiapp.ActiveUIDocument.Document if uiapp.ActiveUIDocument else None
                if self.fenster.dok_schluessel and einstellungen.dokument_schluessel(aktiv) != self.fenster.dok_schluessel:
                    self.fenster.melden("„%s“ nicht ausgeführt: In Revit ist gerade ein anderes Modell aktiv als „%s“. "
                                        "Bitte zu diesem Modell wechseln." % (titel, self.fenster.einst.get("dokument_titel")),
                                        fehler=True)
                    continue
                f(uiapp)
            except Abgebrochen:
                self.fenster.melden("„%s“ abgebrochen." % titel, fehler=True)
            except Exception as e:
                self.fenster.melden("Fehler bei „%s“: %s" % (titel, e), fehler=True)
                self.fenster.log("FEHLER %s\n%s" % (titel, traceback.format_exc()))
        self.fenster.beschaeftigt(False)

    def GetName(self):
        return "Durchbruchskoordination"


def _firmen(ordner):
    """Firmen im Projekt – je Firmenordner nur eine Ereignisdatei lesen (nicht alle Tausende)."""
    namen = set()
    basis = os.path.join(ordner, "ereignisse")
    for unter in (os.listdir(basis) if os.path.isdir(basis) else []):
        dateien = sorted(d for d in os.listdir(os.path.join(basis, unter)) if d.endswith(".json"))
        for d in dateien[:3]:
            try:
                with io.open(os.path.join(basis, unter, d), "r", encoding="utf-8-sig") as f:
                    namen.add(json.load(f)["firma"])
                break
            except (IOError, OSError, ValueError, KeyError):
                continue
    return sorted(namen)


class _Zeile(object):
    def __init__(self, p, text):
        self.id = p["id"]
        self.text = text


class Werkzeug(forms.WPFWindow):

    def __init__(self, doc):
        forms.WPFWindow.__init__(self, XAML)
        self.doc = doc
        self.einst = einstellungen.laden(doc)
        self.dok_schluessel = self.einst.get("dokument")
        self.pruefset = {"typen": []}
        self.plan = None
        self.koord = {}            # oid -> Wirkung (offen/blockiert/freigabe) der Koordination
        self.baum = {}
        self.alle_ebenen = [e["name"] for e in sammeln.alle_ebenen(doc)]
        self.geschoss_vorschlag = sammeln.geschoss_vorschlag(doc)
        self.ebenen_doc = list(self.alle_ebenen)
        self.staende, self.aktiver_stand = [], ""
        self.ansicht_mitglieder = {}   # Stand-ID -> Objekt-IDs, die in seiner 3D-Ansicht sichtbar sind
        self.zustand = None
        self._sperre = False
        self._liste_zeilen = {}
        self.ansichten_3d = sorted(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D) if not v.IsTemplate)
        self._familien_boxen = []
        self._handler = _Warteschlange(self)
        self._ereignis = UI.ExternalEvent.Create(self._handler)
        self.doc_titel = doc.Title

        self.ansichten_bereich = modelle.Ansichten(self, doc)
        self._verbinden()
        self.projekt_zeichnen()
        if self._bereit():
            self._daten_laden()
            self.ansichten_bereich.laden()
            self.einlesen()
        else:
            self.tabs.SelectedItem = self.t_projekt
            self.melden("Willkommen. Bitte zuerst Projektordner, Name, Firma und Rolle festlegen.")
        self._reiter_sichtbarkeit()
        konflikt = einstellungen.projekt_konflikt(self.einst)
        if konflikt:
            self.tabs.SelectedItem = self.t_projekt
            self.melden(konflikt, fehler=True)

    # ================================================================ Grundlagen

    def _verbinden(self):
        self.k_hinweis.Click += lambda s, a: self.naechster_hinweis()
        self.k_revit.Click += lambda s, a: self.in_revit_zeigen()
        self.k_viewer.Click += lambda s, a: self.viewer()
        self.e_viewer.Click += lambda s, a: self.viewer()
        self.k_weiter.Click += lambda s, a: self.weiter()
        self.tabs.SelectionChanged += self._reiter_gewechselt
        self.p_ordner_waehlen.Click += lambda s, a: self._ordner_waehlen()
        self.p_ordner.LostFocus += lambda s, a: (self._rollen_laden(), self._projekt_info_zeigen())
        self.p_speichern.Click += lambda s, a: self.projekt_speichern()
        self.d_familien_ok.Click += lambda s, a: self._familien_uebernehmen()
        self.d_stand.SelectionChanged += lambda s, a: self._stand_gewechselt()
        self.d_stand_neu.Click += lambda s, a: self._stand_neu()
        self.d_stand_weg.Click += lambda s, a: self._stand_loeschen()
        self.d_filter.SelectionChanged += lambda s, a: self.liste_zeichnen()
        self.d_suche.TextChanged += lambda s, a: self.liste_zeichnen()
        self.d_zeigen.Click += lambda s, a: self._auswahl_zeigen()
        self.e_los.Click += lambda s, a: self.einreichen()
        self.e_zurueck.Click += lambda s, a: self.stand_zurueckziehen()
        self.d_ansicht.SelectionChanged += lambda s, a: self._ansicht_gewaehlt()
        self.d_ansicht_lesen.Click += lambda s, a: self._mitglieder_lesen_auftrag()
        self.d_ansicht_neu.Click += lambda s, a: self._stand_ansicht_anlegen()
        self.d_filter.ItemsSource = FILTER
        self.d_filter.SelectedIndex = 0

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
        self.t_ansichten.Visibility = Visibility.Visible if bereit else Visibility.Collapsed
        self.t_durch.Visibility = Visibility.Visible if (bereit and self._ersteller()) else Visibility.Collapsed
        self.t_einreichen.Visibility = Visibility.Visible if (bereit and self._ersteller()) else Visibility.Collapsed
        self.h_projekt.Text = ("✓  Projekt" if bereit else "Projekt")
        self.h_einreichen.Text = "Einreichen" if self._ersteller() else "Veröffentlichen"
        self.e_los.Content = "Einreichen" if self._ersteller() else "Veröffentlichen"
        if bereit:
            self.untertitel.Text = "Projekt „%s“  ·  Modell %s  ·  %s · %s · %s" % (
                self.einst.get("projekt_name") or "?", self.einst["modellkuerzel"], self.einst["name"],
                self._rollenname(self.einst["rolle"]), self.einst["firma"])
        else:
            self.untertitel.Text = "Revit-Modell „%s“ ist noch mit keinem Projekt verbunden" % self.einst.get("dokument_titel", "")

    def _sichtbare_reiter(self):
        return [t for t in (self.t_projekt, self.t_ansichten, self.t_durch, self.t_einreichen)
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
                self.melden("Hinweis: %d abgelehnte Durchbrüche – bitte nacharbeiten oder im Viewer klären." % len(abgelehnt), fehler=True)
                return
            e = self._einordnung()
            if e["neu"] or e["geaendert"] or e["entfaellt"]:
                self.tabs.SelectedItem = self.t_einreichen
                self.melden("Hinweis: Stand „%s“ hat %d neue/geänderte und %d entfallene Durchbrüche – noch nicht eingereicht."
                            % (self._stand()["name"], len(e["neu"]) + len(e["geaendert"]), len(e["entfaellt"])))
                return
        self.melden("Keine offenen Hinweise.")

    # ================================================================ Reiter 1: Projekt

    def projekt_zeichnen(self):
        e = self.einst
        self.p_ordner.Text = e.get("projektordner", "")
        self.p_name.Text = e.get("name", "")
        self.p_firma.Text = e.get("firma", "")
        self.p_kuerzel.Text = e.get("modellkuerzel", "") or ""
        self._projekt_info_zeigen()
        self.p_plant.IsChecked = bool(e.get("plant_durchbrueche"))
        self._rollen_laden(e.get("rolle"))

    def _projekt_info_zeigen(self):
        """Unter dem Ordnerfeld: welches Projekt im Ordner liegt und ob es zu diesem Revit-Modell passt."""
        ordner = (self.p_ordner.Text or "").strip()
        im_modell = self.einst.get("im_modell") or {}
        p = einstellungen.projekt_info(ordner) if ordner else {}
        self.p_projektname.Text = p.get("name") or ""
        self.p_projektname.IsEnabled = bool(p)
        zeilen, fehler = [], False
        if p:
            zeilen.append("Projekt im Ordner: „%s“" % (p.get("name") or "ohne Namen"))
            if im_modell.get("projekt_id") and p.get("id") and im_modell["projekt_id"] != p["id"]:
                zeilen.append("Achtung: Dieses Revit-Modell ist mit Projekt „%s“ verbunden – falscher Ordner?"
                              % (im_modell.get("projekt_name") or "?"))
                fehler = True
        elif ordner:
            zeilen.append("In diesem Ordner gibt es noch kein Projekt – „Übernehmen“ legt eines an.")
        elif im_modell.get("projekt_id"):
            zeilen.append("Dieses Revit-Modell ist mit Projekt „%s“ (Kürzel %s) verbunden. Bitte den Projektordner "
                          "auf diesem Rechner wählen." % (im_modell.get("projekt_name") or "?", im_modell.get("modellkuerzel") or "?"))
        else:
            zeilen.append("Revit-Modell „%s“ ist noch mit keinem Projekt verbunden." % self.einst.get("dokument_titel", ""))
        self.p_projekt_info.Text = "\n".join(zeilen)
        self.p_projekt_info.Foreground = ROT if fehler else GRAU

    def _ordner_waehlen(self):
        pfad = forms.pick_folder(title="Projektordner der Durchbruchskoordination")
        if pfad:
            self.p_ordner.Text = pfad
            self._rollen_laden()
            self._projekt_info_zeigen()

    def _rollen_laden(self, auswahl=None):
        self._rollen = []
        ordner = (self.p_ordner.Text or "").strip()
        pfad = os.path.join(ordner, "projekt.json")
        if os.path.isfile(pfad):
            try:
                with io.open(pfad, "r", encoding="utf-8-sig") as f:
                    self._rollen = json.load(f).get("rollen", [])
                self.p_firma.ItemsSource = _firmen(ordner)
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
        projekt_id = einstellungen.projekt_id_sichern(ordner)
        neuer_name = (self.p_projektname.Text or "").strip()
        alt_name = einstellungen.projekt_info(ordner).get("name")
        if neuer_name and alt_name and neuer_name != alt_name:
            if forms.alert("Projektname für alle Beteiligten ändern?\n\n„%s“  →  „%s“" % (alt_name, neuer_name),
                           title="Projektname", yes=True, no=True):
                einstellungen.projekt_umbenennen(ordner, neuer_name)
        p = einstellungen.projekt_info(ordner)
        im_modell = self.einst.get("im_modell") or {}
        if im_modell.get("projekt_id") and im_modell["projekt_id"] != projekt_id:
            if not forms.alert("Dieses Revit-Modell ist mit Projekt „%s“ verbunden.\nDer gewählte Ordner enthält aber "
                               "Projekt „%s“.\n\nModell wirklich auf das neue Projekt umstellen?"
                               % (im_modell.get("projekt_name") or "?", p.get("name") or "?"),
                               title="Anderes Projekt", yes=True, no=True):
                return
        e = dict(self.einst)
        e["projektordner"] = ordner
        e["projekt_id"] = projekt_id
        e["projekt_name"] = p.get("name") or ""
        e["projekt_id_ordner"] = projekt_id
        e["name"] = (self.p_name.Text or "").strip()
        e["firma"] = (self.p_firma.Text or "").strip()
        e["rolle"] = self._rollen[self.p_rolle.SelectedIndex]["id"] if self.p_rolle.SelectedIndex >= 0 else ""
        e["modellkuerzel"] = einstellungen.kuerzel_bereinigen(self.p_kuerzel.Text)
        e["plant_durchbrueche"] = bool(self.p_plant.IsChecked)
        self.p_kuerzel.Text = e["modellkuerzel"]
        if not (e["name"] and e["firma"] and e["rolle"] and e["modellkuerzel"]):
            self.melden("Bitte Name, Firma, Rolle und Kürzel angeben.", fehler=True)
            return
        e["im_modell"] = {"projekt_id": projekt_id, "projekt_name": e["projekt_name"], "modellkuerzel": e["modellkuerzel"]}
        einstellungen.speichern(e)
        self.einst = e
        ps = sammeln.pruefset_laden(e["projektordner"], e["firma"])
        if not [g for g in (ps.get("geschosse") or []) if g in self.alle_ebenen]:
            ps["geschosse"] = list(self.geschoss_vorschlag)   # Hilfsebenen (OK, UK, RD …) zusammengefasst
        sammeln.pruefset_speichern(e["projektordner"], e["firma"], ps)
        self._reiter_sichtbarkeit()
        self._projekt_info_zeigen()
        self._daten_laden()
        self.ansichten_bereich.laden()

        def binden(uiapp):
            from . import modellbindung
            ok, text = modellbindung.schreiben(uiapp.ActiveUIDocument.Document, projekt_id, e["projekt_name"], e["modellkuerzel"])
            self.log("Projektzuordnung: %s" % (text or "unverändert"))
            if not ok:
                self.melden(text, fehler=True)
        self.auftrag("Projektzuordnung im Modell speichern", binden)
        self.einlesen()
        self.tabs.SelectedItem = self.t_ansichten
        self.melden("Gespeichert – Projekt „%s“." % e["projekt_name"])

    # ================================================================ Daten

    def _daten_laden(self):
        ordner, firma = self._ordner()
        self.pruefset = sammeln.pruefset_laden(ordner, firma)
        gs = set(self.pruefset.get("geschosse") or [])
        self.ebenen_doc = [n for n in self.alle_ebenen if n in gs] or list(self.alle_ebenen)
        self.staende, self.aktiver_stand = staende.laden(ordner, firma, self.einst["modellkuerzel"])

    def einlesen(self):
        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            ordner, firma = self._ordner()
            self.pruefset = sammeln.pruefset_laden(ordner, firma)
            self.baum = sammeln.baum(doc) if self._ersteller() else {}
            self.plan = aktionen.einreichen_planen(doc, self.einst, self.pruefset)
            self._mitglieder_lesen(doc)
            ablage, self.zustand = aktionen.zustand_laden(ordner)
            self.koord = dict((oid, self.zustand.gesamtstatus(oid)["wirkung"]) for oid in self.zustand.objekte)
            self.alles_zeichnen()
            if self._ersteller():
                self.melden("%d Durchbrüche der Koordinations-Familien im Modell gelesen." % len(self.plan.objekte))
            else:
                self.melden("Bereit.")
        self.auftrag("Modell und Projektordner einlesen", f)

    def alles_zeichnen(self):
        if self._ersteller():
            self.familien_zeichnen()
            self.staende_zeichnen()
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

    # ---------------------------------------------------------------- Stände (Name + 3D-Ansicht)

    def _stand(self):
        return next((s for s in self.staende if s["id"] == self.aktiver_stand), None)

    def _staende_sichern(self):
        ordner, firma = self._ordner()
        staende.speichern(ordner, firma, self.einst["modellkuerzel"], self.staende, self.aktiver_stand)

    def staende_zeichnen(self):
        self._sperre = True
        self.d_stand.ItemsSource = [s["name"] for s in self.staende]
        s = self._stand()
        self.d_stand.SelectedItem = s["name"] if s else None
        self.d_ansicht.ItemsSource = self.ansichten_3d
        self.d_ansicht.SelectedItem = s.get("ansicht") if (s and s.get("ansicht") in self.ansichten_3d) else None
        for el in (self.d_ansicht, self.d_ansicht_lesen, self.d_ansicht_neu, self.d_stand_weg):
            el.IsEnabled = s is not None
        self._sperre = False
        self.liste_zeichnen()

    def _stand_gewechselt(self):
        if self._sperre:
            return
        name = self.d_stand.SelectedItem
        s = next((x for x in self.staende if x["name"] == name), None)
        self.aktiver_stand = s["id"] if s else ""
        self._staende_sichern()
        self.staende_zeichnen()
        if s and s.get("ansicht") and s["id"] not in self.ansicht_mitglieder:
            self._mitglieder_lesen_auftrag()

    def _stand_neu(self):
        name = forms.ask_for_string(default="", prompt="Name des Stands (so sehen ihn alle im Viewer):", title="Neuer Stand")
        name = (name or "").strip()
        if not name:
            return
        if any(s["name"] == name for s in self.staende):
            self.melden("Einen Stand mit diesem Namen gibt es schon.", fehler=True)
            return
        s = staende.neu(name)
        vorschlag = "DBK Stand – %s" % name
        if vorschlag in self.ansichten_3d:
            s["ansicht"] = vorschlag
        self.staende.append(s)
        self.aktiver_stand = s["id"]
        self._staende_sichern()
        self.staende_zeichnen()
        self.melden("Stand „%s“ angelegt. Jetzt eine 3D-Ansicht wählen oder mit „Ansicht anlegen“ erzeugen." % name)

    def _stand_loeschen(self):
        s = self._stand()
        if s is None:
            return
        eingereicht = any(o.besitzer == self.einst["firma"] and o.stand == s["name"]
                          for o in (self.zustand.objekte.values() if self.zustand else []))
        text = "Stand „%s“ hier aus der Liste löschen?" % s["name"]
        if eingereicht:
            text += ("\n\nEr ist schon eingereicht – im Viewer bleibt er bestehen. Zum Entfernen für alle "
                     "im Reiter „Einreichen“ auf „Stand zurückziehen“.")
        if forms.alert(text, yes=True, no=True):
            self.staende.remove(s)
            self.aktiver_stand = ""
            self._staende_sichern()
            self.staende_zeichnen()

    def _ansicht_gewaehlt(self):
        if self._sperre:
            return
        s = self._stand()
        if s is None or self.d_ansicht.SelectedItem is None:
            return
        s["ansicht"] = self.d_ansicht.SelectedItem
        self._staende_sichern()
        self._mitglieder_lesen_auftrag()

    def _mitglieder_lesen(self, doc):
        """Je Stand: welche Durchbrüche (der Koordinations-Familien) sind in seiner 3D-Ansicht sichtbar?"""
        if self.plan is None:
            return
        nach_element = dict((eid(i), o) for o, i in self.plan.element_ids.items())
        ansichten = dict((v.Name, v) for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D) if not v.IsTemplate)
        self.ansichten_3d = sorted(ansichten)
        self.ansicht_mitglieder = {}
        for s in self.staende:
            if s.get("ansicht") not in ansichten:
                continue
            sichtbar = set()
            for e in DB.FilteredElementCollector(doc, ansichten[s["ansicht"]].Id).WhereElementIsNotElementType():
                o = nach_element.get(eid(e.Id))
                if o is not None:
                    sichtbar.add(o)
            self.ansicht_mitglieder[s["id"]] = sichtbar

    def _mitglieder_lesen_auftrag(self):
        def f(uiapp):
            self._mitglieder_lesen(uiapp.ActiveUIDocument.Document)
            self.staende_zeichnen()
            s = self._stand()
            if s is not None:
                self.melden("„%s“: %d Durchbrüche in der Ansicht sichtbar." % (s.get("ansicht"), len(self._mitglieder())))
        self.auftrag("3D-Ansicht lesen", f)

    def _stand_ansicht_anlegen(self):
        s = self._stand()
        if s is None or self.plan is None:
            self.melden("Bitte zuerst einen Stand wählen oder anlegen.", fehler=True)
            return
        vorher = self._mitglieder()
        sichtbar = [self.plan.element_ids[o] for o in (vorher or self.plan.objekte)]
        alle = [self.plan.element_ids[o] for o in self.plan.objekte]
        name = "DBK Stand – %s" % s["name"]

        def f(uiapp):
            uidoc = uiapp.ActiveUIDocument
            doc = uidoc.Document
            kats = set(eid(doc.GetElement(i).Category.Id) for i in alle)
            behalten = set(eid(i) for i in sichtbar)
            with DB.Transaction(doc, "DBK: Stand-Ansicht") as t:
                t.Start()
                ansicht = next((x for x in DB.FilteredElementCollector(doc).OfClass(DB.View3D)
                                if not x.IsTemplate and x.Name == name), None)
                if ansicht is None:
                    vft = next(x for x in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                               if x.ViewFamily == DB.ViewFamily.ThreeDimensional)
                    ansicht = DB.View3D.CreateIsometric(doc, vft.Id)
                    ansicht.Name = name
                pakete._grundeinstellung(doc, ansicht, kats)
                elemente = [e for e in DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
                            if e.Category is not None and eid(e.Category.Id) in kats and e.CanBeHidden(ansicht)]
                versteckt = [e.Id for e in elemente if e.IsHidden(ansicht)]
                if versteckt:
                    ansicht.UnhideElements(sammeln._liste(versteckt))
                weg = [e.Id for e in elemente if eid(e.Id) not in behalten]
                if weg:
                    ansicht.HideElements(sammeln._liste(weg))
                t.Commit()
            uidoc.ActiveView = ansicht
            s["ansicht"] = name
            self._staende_sichern()
            self._mitglieder_lesen(doc)
            self.staende_zeichnen()
            self.melden("„%s“ angelegt: %d Durchbrüche. In Revit ausblenden, was nicht zum Stand gehört, dann „Neu lesen“."
                        % (name, len(sichtbar)))
        self.auftrag("Stand-Ansicht anlegen", f)

    # ---------------------------------------------------------------- Liste des Stands

    def _mitglieder(self):
        """Objekt-IDs, die beim Einreichen zum Stand gehören (sichtbar in der Ansicht, nicht fremd)."""
        s = self._stand()
        if s is None or self.plan is None:
            return []
        sichtbar = self.ansicht_mitglieder.get(s["id"], set())
        return [o for o in self.plan.objekte if o in sichtbar and self.plan.zustand[o] != aktionen.FREMD]

    def _einordnung(self):
        """{"neu", "geaendert", "daten", "unveraendert", "entfaellt", "fremd"} -> Objekt-IDs für den aktuellen Stand."""
        s = self._stand()
        e = dict((k, []) for k in ("neu", "geaendert", "daten", "unveraendert", "entfaellt", "fremd"))
        if s is None or self.plan is None:
            return e
        sichtbar = self.ansicht_mitglieder.get(s["id"], set())
        art = {aktionen.NEU: "neu", aktionen.GEOMETRIE: "geaendert", aktionen.DATEN: "daten",
               aktionen.UNVERAENDERT: "unveraendert", aktionen.FREMD: "fremd"}
        for o in self.plan.objekte:
            if o in sichtbar:
                e[art[self.plan.zustand[o]]].append(o)
        mitglieder = set(self._mitglieder())
        if self.zustand is not None:
            for oid, o in self.zustand.objekte.items():
                if o.besitzer == self.einst["firma"] and o.stand == s["name"] and oid not in mitglieder:
                    e["entfaellt"].append(oid)
        return e

    def _zeilentext(self, oid, art):
        d = self.plan.objekte.get(oid) or (self.zustand.objekte[oid].daten if oid in self.zustand.objekte else {})
        w = d.get("wirt") or {}
        wirt = {"Wände": "Wand", "Geschossdecken": "Decke", "Dächer": "Dach"}.get(w.get("kategorie"), w.get("kategorie") or "")
        if w.get("tragend"):
            wirt += " tragend"
        k = self.koord.get(oid)
        zusatz = ""
        if art == "unveraendert":
            zusatz = " · " + KOORD_TEXT.get(k, "in Prüfung")
        elif art == "geaendert" and k:
            zusatz = " · Prüfung beginnt neu"
        alt = self.zustand.objekte.get(oid) if self.zustand else None
        if alt is not None and alt.stand and alt.stand != (self._stand() or {}).get("name") and art != "entfaellt":
            zusatz += " · bisher in „%s“" % alt.stand
        return "%s  ·  %s  ·  %s  ·  %s%s" % (d.get("nummer"), d.get("groesse"), wirt, ART_TEXT[art], zusatz)

    def liste_zeichnen(self):
        self.d_liste.Items.Clear()
        self._liste_zeilen = {}
        einordnung = self._einordnung()
        filt = FILTER_ARTEN[self.d_filter.SelectedIndex] if self.d_filter.SelectedIndex >= 0 else None
        such = (self.d_suche.Text or "").strip().lower()
        gruppen = {}
        for art in ("neu", "geaendert", "daten", "unveraendert", "entfaellt", "fremd"):
            if filt and art not in filt:
                continue
            for oid in einordnung[art]:
                text = self._zeilentext(oid, art)
                d = self.plan.objekte.get(oid) or self.zustand.objekte[oid].daten
                if such and such not in (text + " " + (d.get("familie") or "")).lower():
                    continue
                gruppen.setdefault(d.get("ebene"), []).append((oid, text, art, d))
        for ebene in sorted(gruppen, key=lambda n: self.ebenen_doc.index(n) if n in self.ebenen_doc else 999):
            knoten = TreeViewItem()
            knoten.Header = "%s  (%d)" % (ebene, len(gruppen[ebene]))
            knoten.IsExpanded = len(gruppen) <= 3 or bool(filt and "unveraendert" not in filt)
            for oid, text, art, d in sorted(gruppen[ebene], key=lambda x: x[3].get("nummer") or ""):
                t = TextBlock()
                t.Text = text
                t.Tag = oid
                if self.koord.get(oid) == "blockiert":
                    t.Foreground = ROT
                elif art in ("neu", "geaendert"):
                    t.Foreground = ORANGE
                elif art in ("entfaellt", "fremd"):
                    t.Foreground = GRAU
                    t.TextDecorations = System.Windows.TextDecorations.Strikethrough if art == "entfaellt" else None
                elif self.koord.get(oid) == "freigabe":
                    t.Foreground = GRUEN
                item = TreeViewItem()
                item.Header = t
                knoten.Items.Add(item)
                self._liste_zeilen[oid] = t
            self.d_liste.Items.Add(knoten)
        self._summe(einordnung)

    def _summe(self, einordnung=None):
        e = einordnung or self._einordnung()
        s = self._stand()
        if s is None:
            self.d_summe.Text = "Kein Stand gewählt"
            self.h_durch.Text = "Durchbrüche"
            return
        if not s.get("ansicht"):
            self.d_summe.Text = "Noch keine 3D-Ansicht gewählt"
            self.h_durch.Text = "Durchbrüche"
            return
        teile = ["%d %s" % (len(e[k]), t) for k, t in (("neu", "neu"), ("geaendert", "geändert"), ("daten", "Daten geändert"),
                                                       ("unveraendert", "unverändert"), ("entfaellt", "entfallen"),
                                                       ("fremd", "anderer Firma")) if e[k]]
        self.d_summe.Text = " · ".join(teile) or "Keine Durchbrüche in der Ansicht sichtbar"
        n = len(e["neu"]) + len(e["geaendert"])
        self.h_durch.Text = "Durchbrüche  (%d)" % n if n else "Durchbrüche"

    def _auswahl_zeigen(self):
        if self.plan is None or self._stand() is None:
            return
        e = self._einordnung()
        alle = [self.plan.element_ids[o] for o in self._mitglieder()]
        neu = [self.plan.element_ids[o] for o in e["neu"] + e["geaendert"]]

        def f(uiapp):
            ansichten.kontrollansicht(uiapp.ActiveUIDocument, self.einst, alle, neu)
            self.melden("Kontrollansicht: orange = neu/geändert, grau = unverändert.")
        self.auftrag("Stand in Revit zeigen", f)

    # ================================================================ Reiter 3: Einreichen

    def zusammenfassung_zeichnen(self):
        if not self._bereit():
            return
        s = self._stand() if self._ersteller() else None
        if s is None:
            self.e_zusammenfassung.Text = "Bitte im Reiter „Durchbrüche“ einen Stand wählen."
            self.e_runde_box.Visibility = Visibility.Collapsed
            self.e_los.IsEnabled = self.e_zurueck.IsEnabled = False
            return
        e = self._einordnung()
        n_mit = len(self._mitglieder())
        zeilen = ["Stand „%s“ aus 3D-Ansicht „%s“ – %d Durchbrüche:" % (s["name"], s.get("ansicht") or "–", n_mit),
                  "•  %d neu, %d geändert (Lage/Größe) – gehen in die Prüfung" % (len(e["neu"]), len(e["geaendert"])),
                  "•  %d unverändert – bleiben, Entscheidungen gelten weiter" % len(e["unveraendert"])]
        if e["daten"]:
            zeilen.append("•  %d nur Daten geändert (z. B. Nummer) – Entscheidungen gelten weiter" % len(e["daten"]))
        if e["entfaellt"]:
            zeilen.append("•  %d nicht mehr in der Ansicht – fallen aus der Koordination heraus" % len(e["entfaellt"]))
        if e["fremd"]:
            zeilen.append("•  %d gehören einer anderen Firma – werden nicht eingereicht" % len(e["fremd"]))
        zeilen.append("")
        zeilen.append("Modelle und Pläne für den Viewer laufen getrennt über den Reiter „Ansichten“.")
        self.e_zusammenfassung.Text = "\n".join(zeilen)
        pruefen = bool(e["neu"] or e["geaendert"])
        self.e_runde_box.Visibility = Visibility.Visible if pruefen else Visibility.Collapsed
        if not (self.e_runde.Text or "").strip():
            self.e_runde.Text = "Prüfrunde %s" % time.strftime("%d.%m.%Y")
        self.e_los.IsEnabled = bool(n_mit or e["entfaellt"])
        self.e_los.Content = "Stand „%s“ einreichen" % s["name"]
        eingereicht = self.zustand is not None and ("%s|%s" % (self.einst["firma"], s["name"])) in self.zustand.staende \
            or any(o.besitzer == self.einst["firma"] and o.stand == s["name"] for o in (self.zustand.objekte.values() if self.zustand else []))
        self.e_zurueck.IsEnabled = bool(eingereicht)

    def einreichen(self):
        s = self._stand()
        if s is None:
            self.melden("Bitte zuerst einen Stand wählen.", fehler=True)
            return
        if not s.get("ansicht"):
            self.melden("Der Stand hat noch keine 3D-Ansicht.", fehler=True)
            return
        e = self._einordnung()
        if not self._mitglieder() and not forms.alert(
                "In der Ansicht ist kein Durchbruch sichtbar.\nStand „%s“ trotzdem einreichen? Alle bisher eingereichten "
                "Durchbrüche dieses Stands fallen dann heraus." % s["name"], yes=True, no=True):
            return
        runde = (self.e_runde.Text or "").strip()
        if (e["neu"] or e["geaendert"]) and not runde:
            self.melden("Bitte einen Namen für die Prüfrunde angeben.", fehler=True)
            return

        def f(uiapp):
            doc = uiapp.ActiveUIDocument.Document
            with Fortschritt("Stand einreichen", ["Durchbrüche lesen", "Ansicht lesen", "In den Projektordner schreiben"]) as fs:
                fs.schritt(0, "Lage, Größe und Bauteil je Durchbruch …")
                self.plan = aktionen.einreichen_planen(doc, self.einst, self.pruefset,
                                                       fortschritt=lambda i, n: fs.menge(i, n, "Durchbrüche"))
                fs.schritt(1, "3D-Ansicht „%s“" % s["ansicht"])
                self._mitglieder_lesen(doc)
                mitglieder = self._mitglieder()
                fs.schritt(2, "%d Durchbrüche" % len(mitglieder))
                r = aktionen.stand_einreichen(self.einst, self.plan, s["name"], mitglieder, rundenname=runde)
                fs.fertig()
                fs.detail("%d neu, %d geändert, %d unverändert, %d entfallen." % (r["neu"], r["geaendert"], r["unveraendert"], r["entfallen"]))
            self.log("Stand „%s“: %d neu, %d geändert, %d unverändert, %d entfallen (Runde „%s“)."
                     % (s["name"], r["neu"], r["geaendert"], r["unveraendert"], r["entfallen"], runde or "–"))
        self.auftrag("Einreichen", f)
        self.einlesen()

    def stand_zurueckziehen(self):
        s = self._stand()
        if s is None:
            return
        if not forms.alert("Stand „%s“ für alle zurückziehen?\n\nAlle Durchbrüche dieses Stands verschwinden aus der "
                           "Koordination (auch die Prüf-Entscheidungen). Erneutes Einreichen beginnt von vorn."
                           % s["name"], title="Stand zurückziehen", yes=True, no=True):
            return
        aktionen.stand_zurueckziehen(self.einst, s["name"])
        self.log("Stand „%s“ zurückgezogen." % s["name"])
        self.einlesen()

    # ================================================================ Werkzeugleiste

    def in_revit_zeigen(self):
        item = self.d_liste.SelectedItem
        oid = item.Header.Tag if (item is not None and isinstance(item.Header, TextBlock)) else None
        if oid is None or self.plan is None or oid not in self.plan.objekte:
            self.melden("Bitte im Reiter „Durchbrüche“ eine Zeile eines vorhandenen Durchbruchs markieren.", fehler=True)
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
