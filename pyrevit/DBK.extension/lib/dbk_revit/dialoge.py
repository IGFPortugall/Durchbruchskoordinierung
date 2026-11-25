# -*- coding: utf-8 -*-
"""Dialoge: Anmelden und Prüfset."""
from __future__ import unicode_literals

import io
import json
import os

from System.Windows import Visibility
from System.Windows.Controls import CheckBox, TreeViewItem
from pyrevit import forms

from dbk_core import Ablage
from . import ansichten, einstellungen, sammeln

UI_ORDNER = os.path.join(os.path.dirname(__file__), "ui")


class Anmelden(forms.WPFWindow):
    """Name, Firma, Rolle, Projektordner, Modellkürzel und Ansichtsvorlagen."""

    def __init__(self, doc):
        forms.WPFWindow.__init__(self, os.path.join(UI_ORDNER, "anmelden.xaml"))
        self.doc = doc
        self.ergebnis = None
        e = einstellungen.laden()
        self.e = e
        self.ordner.Text = e.get("projektordner", "")
        self.name.Text = e.get("name", "")
        self.firma.Text = e.get("firma", "")
        self.kuerzel.Text = e.get("modellkuerzel", "") or "HLS"
        self.viewer_url.Text = e.get("viewer_url", "")
        leer = "(keine Vorlage)"
        self.vorlage_2d.ItemsSource = [leer] + (ansichten.vorlagen(doc, True) if doc else [])
        self.vorlage_3d.ItemsSource = [leer] + (ansichten.vorlagen(doc, False) if doc else [])
        self.vorlage_2d.SelectedItem = e.get("vorlage_2d") or leer
        self.vorlage_3d.SelectedItem = e.get("vorlage_3d") or leer
        self._rollen_laden(e.get("rolle"))
        self.ordner.LostFocus += lambda s, a: self._rollen_laden(None)
        self.knopf_ordner.Click += self._ordner_waehlen
        self.knopf_ok.Click += self._ok
        self.knopf_abbrechen.Click += lambda s, a: self.Close()

    def _ordner_waehlen(self, sender, args):
        pfad = forms.pick_folder(title="Projektordner der Durchbruchskoordinierung")
        if pfad:
            self.ordner.Text = pfad
            self._neues_projekt_anbieten()
            self._rollen_laden(None)

    def _neues_projekt_anbieten(self):
        """Fehlt projekt.json, kann hier ein neues Projekt angelegt werden. Gibt True zurück, wenn es eins gibt."""
        ordner = (self.ordner.Text or "").strip()
        if not ordner or not os.path.isdir(ordner):
            return False
        if os.path.isfile(os.path.join(ordner, "projekt.json")):
            return True
        frage = ("In diesem Ordner gibt es noch kein Projekt:\n%s\n\n"
                 "Hier ein neues Projekt für die Durchbruchskoordinierung anlegen?\n"
                 "(Standard-Rollen TGA, Elektro, Labor, Architektur, Tragwerk, Brandschutz, Bauherr – "
                 "später in der Verwaltung änderbar.)\n\n"
                 "Wenn andere das Projekt schon angelegt haben, bitte stattdessen deren Ordner wählen." % ordner)
        if not forms.alert(frage, title="DBK – Neues Projekt", yes=True, no=True):
            return False
        name = forms.ask_for_string(default=self.doc.Title if self.doc else os.path.basename(ordner),
                                    prompt="Projektname:", title="DBK – Neues Projekt")
        if not name:
            return False
        einstellungen.projekt_anlegen(ordner, name)
        return True

    def _rollen_laden(self, auswahl):
        self._rollen = []
        pfad = os.path.join(self.ordner.Text or "", "projekt.json")
        try:
            with io.open(pfad, "r", encoding="utf-8-sig") as f:
                self._rollen = json.load(f).get("rollen", [])
            self.meldung.Text = ""
            firmen = set()
            a = Ablage(self.ordner.Text)
            a.lade_neue()
            for ev in a.alle():
                firmen.add(ev["firma"])
            self.firma.ItemsSource = sorted(firmen)
        except (IOError, OSError, ValueError):
            if self.ordner.Text:
                self.meldung.Text = "Hier gibt es noch kein Projekt – beim Speichern können Sie eins anlegen."
        alt = auswahl or (self.rolle.SelectedItem and self.rolle.SelectedItem.split(" ")[0])
        self.rolle.ItemsSource = ["%s  (%s)" % (r["id"], r["name"]) for r in self._rollen]
        for i, r in enumerate(self._rollen):
            if r["id"] == alt:
                self.rolle.SelectedIndex = i

    def _ok(self, sender, args):
        e = dict(self.e)
        e["projektordner"] = (self.ordner.Text or "").strip()
        e["name"] = (self.name.Text or "").strip()
        e["firma"] = (self.firma.Text or "").strip()
        e["rolle"] = self._rollen[self.rolle.SelectedIndex]["id"] if self.rolle.SelectedIndex >= 0 else ""
        e["modellkuerzel"] = einstellungen.kuerzel_bereinigen(self.kuerzel.Text)
        self.kuerzel.Text = e["modellkuerzel"]
        e["vorlage_2d"] = "" if self.vorlage_2d.SelectedIndex <= 0 else self.vorlage_2d.SelectedItem
        e["vorlage_3d"] = "" if self.vorlage_3d.SelectedIndex <= 0 else self.vorlage_3d.SelectedItem
        e["viewer_url"] = (self.viewer_url.Text or "").strip()
        if not os.path.isfile(os.path.join(e["projektordner"], "projekt.json")):
            if not self._neues_projekt_anbieten():
                self.meldung.Text = "Bitte einen Projektordner mit projekt.json wählen oder hier ein neues Projekt anlegen."
                return
            self._rollen_laden(None)
            if self.rolle.SelectedIndex < 0:
                self.meldung.Text = "Projekt angelegt. Bitte jetzt Ihre Rolle wählen und erneut speichern."
                return
            e["rolle"] = self._rollen[self.rolle.SelectedIndex]["id"]
        if not einstellungen.vollstaendig(e):
            self.meldung.Text = "Bitte Projektordner (mit projekt.json), Name, Firma und Rolle angeben."
            return
        if not e["modellkuerzel"]:
            self.meldung.Text = "Bitte ein Kürzel für dieses Modell angeben, z. B. HLS."
            return
        einstellungen.speichern(e)
        self.ergebnis = e
        self.Close()


class Pruefset(forms.WPFWindow):
    """Baum Kategorie → Familie → Typ mit Häkchen."""

    def __init__(self, doc, einst):
        forms.WPFWindow.__init__(self, os.path.join(UI_ORDNER, "pruefset.xaml"))
        self.doc, self.einst = doc, einst
        self.gespeichert = False
        alt = sammeln.pruefset_laden(einst["projektordner"], einst["firma"])
        gewaehlt = set((t["kategorie"], t["familie"], t["typ"]) for t in alt.get("typen", []))
        self._typen = []   # (CheckBox, kategorie, familie, typ, anzahl)
        daten = sammeln.baum(doc)
        for kat in sorted(daten):
            k_item, k_box = self._knoten(kat, None)
            for fam in sorted(daten[kat]):
                f_item, f_box = self._knoten(fam, k_box)
                for typ in sorted(daten[kat][fam]):
                    n = daten[kat][fam][typ]
                    t_item, t_box = self._knoten("%s  (%d)" % (typ, n), f_box)
                    t_box.IsChecked = (kat, fam, typ) in gewaehlt
                    t_box.Checked += lambda s, a: self._summe()
                    t_box.Unchecked += lambda s, a: self._summe()
                    self._typen.append((t_box, kat, fam, typ, n, t_item))
                    f_item.Items.Add(t_item)
                k_item.Items.Add(f_item)
                if any((kat, fam, t) in gewaehlt for t in daten[kat][fam]):
                    k_item.IsExpanded = True
            self.baum.Items.Add(k_item)
        self.suche.TextChanged += self._filtern
        self.knopf_ok.Click += self._ok
        self.knopf_abbrechen.Click += lambda s, a: self.Close()
        self._summe()

    def _knoten(self, text, eltern_box):
        item = TreeViewItem()
        box = CheckBox()
        box.Content = text
        item.Header = box
        box.Tag = []
        if eltern_box is not None:
            eltern_box.Tag.append(box)

        def umschalten(s, a):
            for kind in box.Tag:
                kind.IsChecked = box.IsChecked
        box.Click += umschalten
        return item, box

    def _filtern(self, sender, args):
        such = (self.suche.Text or "").lower()
        for box, kat, fam, typ, n, item in self._typen:
            treffer = not such or such in (fam + " " + typ).lower()
            item.Visibility = Visibility.Visible if treffer else Visibility.Collapsed
            if such and treffer:
                item.Parent.IsExpanded = True
                item.Parent.Parent.IsExpanded = True

    def _summe(self):
        n = sum(t[4] for t in self._typen if t[0].IsChecked)
        k = sum(1 for t in self._typen if t[0].IsChecked)
        self.summe.Text = "%d Typen · %d Bauteile" % (k, n)

    def _ok(self, sender, args):
        typen = [{"kategorie": kat, "familie": fam, "typ": typ}
                 for box, kat, fam, typ, n, item in self._typen if box.IsChecked]
        daten = sammeln.pruefset_laden(self.einst["projektordner"], self.einst["firma"])
        daten.update({"modell": self.einst.get("modellkuerzel"), "typen": typen})   # Ausschlüsse/Exporte bleiben
        sammeln.pruefset_speichern(self.einst["projektordner"], self.einst["firma"], daten)
        self.gespeichert = True
        self.Close()
