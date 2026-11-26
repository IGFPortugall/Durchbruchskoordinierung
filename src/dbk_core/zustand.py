# -*- coding: utf-8 -*-
"""Berechnet den aktuellen Stand aller Prüfobjekte aus den Ereignissen.

Regeln:
  - Ein Objekt gehört der Firma, die es zuerst eingereicht hat. Nur diese darf
    es ändern, erneut einreichen oder löschen.
  - Gelöscht ist gelöscht: das Objekt verschwindet aus dem Ergebnis
    (es sei denn, der Besitzer reicht es später neu ein).
  - Je Rolle zählt nur die letzte Entscheidung, und nur wenn sie zum aktuellen
    geometrie_hash passt. Geometrie geändert -> alte Entscheidungen ungültig.
  - Gesamtstatus: blockierende Entscheidung einer Pflichtrolle -> deren Status;
    alle Pflichtrollen freigegeben -> "freigegeben"; sonst "in_pruefung".
"""
from __future__ import unicode_literals

from . import ereignisse as ev
from .projekt import BLOCKIERT, FREIGABE, OFFEN, PFLICHT

IN_PRUEFUNG = "in_pruefung"
FREIGEGEBEN = "freigegeben"


class ObjektZustand(object):

    def __init__(self, objekt_id):
        self.id = objekt_id
        self.daten = None            # letzter Stand der Objektdaten
        self.besitzer = None         # Firma, die eingereicht hat
        self.ersteller_rolle = None
        self.geloescht = False
        self.runden = []             # IDs der Prüfrunden, in denen es eingereicht wurde
        self.stand = None            # Name des Stands beim letzten Einreichen
        self.einreichung = None      # bei der letzten Stand-Einreichung: "neu" | "geaendert" | "unveraendert"
        self.letzte_einreichung = None   # Sortierschlüssel
        self.entscheidungen = {}     # Rolle -> letztes Status-Ereignis
        self.verlauf = []            # alle Ereignisse zu diesem Objekt (Chat + Status)

    @property
    def geometrie_hash(self):
        return (self.daten or {}).get("geometrie_hash")

    def gueltige_entscheidung(self, rolle):
        e = self.entscheidungen.get(rolle)
        if e is not None and e["daten"].get("geometrie_hash") == self.geometrie_hash:
            return e
        return None


class Zustand(object):

    def __init__(self, projekt):
        self.projekt = projekt
        self.objekte = {}    # nur aktive (eingereicht, nicht gelöscht)
        self.runden = {}     # Runden-ID -> Daten der Runde
        self.modelle = {}    # Modell-Kürzel -> {"besitzer", "aktuell", "versionen"}
        self.staende = {}    # "<Firma>|<Stand>" -> {"firma", "stand", "zeit", "runde", "anzahl"}
        self.ignoriert = []  # Ereignisse, die gegen die Regeln verstoßen

    # ------------------------------------------------------------ Auswertung

    def beteiligung(self, objekt_id):
        return self.projekt.beteiligung(self.objekte[objekt_id].daten)

    def gesamtstatus(self, objekt_id):
        """dict mit status, wirkung, pflicht_erfuellt, pflicht_gesamt, geaendert, rollen."""
        o = self.objekte[objekt_id]
        beteiligung = self.projekt.beteiligung(o.daten)
        pflicht = sorted(r for r, s in beteiligung.items() if s == PFLICHT)

        rollen = {}
        for rolle in sorted(set(beteiligung) | set(o.entscheidungen)):
            g = o.gueltige_entscheidung(rolle)
            rollen[rolle] = {
                "stufe": beteiligung.get(rolle),
                "status": g["daten"]["wert"] if g else None,
                "wirkung": self.projekt.wirkung(g["daten"]["wert"]) if g else None,
                "veraltet": o.entscheidungen.get(rolle) is not None and g is None,
            }

        blockierend = [o.gueltige_entscheidung(r) for r in pflicht
                       if rollen[r]["wirkung"] == BLOCKIERT]
        erfuellt = len([r for r in pflicht if rollen[r]["wirkung"] == FREIGABE])

        if blockierend:
            letzte = sorted(blockierend, key=ev.sortierschluessel)[-1]
            status = letzte["daten"]["wert"]
            wirkung = BLOCKIERT
        elif pflicht and erfuellt == len(pflicht):
            status, wirkung = FREIGEGEBEN, FREIGABE
        else:
            status, wirkung = IN_PRUEFUNG, OFFEN

        return {
            "status": status,
            "wirkung": wirkung,
            "pflicht_erfuellt": erfuellt,
            "pflicht_gesamt": len(pflicht),
            "geaendert": any(r["veraltet"] for r in rollen.values()),
            "rollen": rollen,
        }

    def wartet_auf(self, firma=None, rolle=None):
        """IDs der Objekte, bei denen diese Firma/Rolle als Nächstes etwas tun muss.

        Prüfer (rolle): Pflichtrolle ohne gültige Entscheidung, oder nach einer
        nicht-freigebenden Entscheidung wurde erneut eingereicht.
        Ersteller (firma): eigenes Objekt ist blockiert und wurde seitdem nicht
        erneut eingereicht.
        """
        ergebnis = []
        for oid in sorted(self.objekte):
            o = self.objekte[oid]
            if rolle is not None and self._wartet_auf_pruefer(o, rolle):
                ergebnis.append(oid)
            elif firma is not None and o.besitzer == firma and self._wartet_auf_ersteller(o):
                ergebnis.append(oid)
        return ergebnis

    def _wartet_auf_pruefer(self, o, rolle):
        if self.projekt.beteiligung(o.daten).get(rolle) != PFLICHT:
            return False
        g = o.gueltige_entscheidung(rolle)
        if g is None:
            return True
        if self.projekt.wirkung(g["daten"]["wert"]) == FREIGABE:
            return False
        return o.letzte_einreichung is not None and o.letzte_einreichung > ev.sortierschluessel(g)

    def _wartet_auf_ersteller(self, o):
        gs = self.gesamtstatus(o.id)
        if gs["wirkung"] != BLOCKIERT:
            return False
        letzte_ablehnung = max(ev.sortierschluessel(o.gueltige_entscheidung(r))
                               for r, info in gs["rollen"].items()
                               if info["wirkung"] == BLOCKIERT and info["stufe"] == PFLICHT)
        return o.letzte_einreichung is None or o.letzte_einreichung < letzte_ablehnung


def _stand_eingereicht(z, alle, e):
    """Momentaufnahme eines Stands.

    - ``objekte`` (Neue/Geänderte): wie „eingereicht“; bei gleichem geometrie_hash nur Datenabgleich
      (zählt nicht als erneute Einreichung, Entscheidungen bleiben).
    - übrige ``mitglieder``: bestätigt („unverändert“), gehören jetzt zu diesem Stand.
    - Objekte der Firma, die bisher zu diesem Stand gehörten und fehlen, fallen heraus.
    """
    firma, d = e["firma"], e["daten"]
    stand = d["stand"] or None
    objekte = d.get("objekte") or {}
    mitglieder = set(d.get("mitglieder") or [])
    schluessel = ev.sortierschluessel(e)
    runde = d.get("runde")
    anzahl = 0
    for oid in sorted(mitglieder):
        o = alle.get(oid)
        neu_daten = objekte.get(oid)
        if neu_daten is not None:
            if o is None:
                o = alle[oid] = ObjektZustand(oid)
            if o.besitzer is None:
                o.besitzer, o.ersteller_rolle = firma, e["rolle"]
            if o.besitzer != firma:
                continue
            war_aktiv = o.daten is not None and not o.geloescht
            if war_aktiv and o.geometrie_hash == neu_daten.get("geometrie_hash"):
                o.einreichung = "unveraendert"
            else:
                o.einreichung = "geaendert" if war_aktiv else "neu"
                o.letzte_einreichung = schluessel
                if runde and runde not in o.runden:
                    o.runden.append(runde)
                o.verlauf.append(dict(e, art=ev.EINGEREICHT, objekt=oid,
                                      daten={"objekt": neu_daten, "runde": runde, "stand": d["stand"],
                                             "einreichung": o.einreichung}))
            o.daten = dict(neu_daten)
            o.geloescht = False
        else:
            if o is None or o.besitzer != firma or o.daten is None or o.geloescht:
                continue                    # Unverändert geht nur für Bestehendes
            o.einreichung = "unveraendert"
        o.stand = stand
        anzahl += 1
    for oid, o in alle.items():
        if o.besitzer == firma and o.stand == stand and not o.geloescht and oid not in mitglieder:
            o.geloescht = True
    z.staende["%s|%s" % (firma, d["stand"])] = {"firma": firma, "stand": d["stand"], "zeit": e["zeit"],
                                                "runde": runde, "anzahl": anzahl}


def berechne(ereignisse, projekt):
    """Faltet alle Ereignisse (beliebige Reihenfolge) zu einem ``Zustand``."""
    z = Zustand(projekt)
    alle = {}

    for e in sorted(ereignisse, key=ev.sortierschluessel):
        art = e["art"]
        if art == ev.PRUEFRUNDE_GESTARTET:
            d = dict(e["daten"])
            d["firma"] = e["firma"]
            d["gestartet"] = e["zeit"]
            if d.get("runde"):
                z.runden[d["runde"]] = d
            continue
        if art == ev.MODELL_VEROEFFENTLICHT:
            d = dict(e["daten"])
            d["firma"] = e["firma"]
            d["veroeffentlicht"] = e["zeit"]
            m = z.modelle.setdefault(d["modell"], {"besitzer": e["firma"], "aktuell": None,
                                                   "versionen": [], "ausrichtung": None})
            if m["besitzer"] != e["firma"]:
                z.ignoriert.append(e)
                continue
            m["versionen"].append(d)
            m["aktuell"] = d
            continue
        if art == ev.MODELL_AUSRICHTUNG:
            m = z.modelle.get(e["daten"]["modell"])
            if m is None or m["besitzer"] != e["firma"]:
                z.ignoriert.append(e)
                continue
            m["ausrichtung"] = dict(e["daten"])
            continue
        if art == ev.MODELL_ENTFERNT:
            m = z.modelle.get(e["daten"]["modell"])
            if m is None or m["besitzer"] != e["firma"]:
                z.ignoriert.append(e)
                continue
            del z.modelle[e["daten"]["modell"]]   # gelöscht ist gelöscht; neu veröffentlichen beginnt von vorn
            continue
        if art == ev.STAND_EINGEREICHT:
            _stand_eingereicht(z, alle, e)
            continue
        if art == ev.STAND_ZURUECKGEZOGEN:
            stand = e["daten"]["stand"] or None
            for o in alle.values():
                if o.besitzer == e["firma"] and not o.geloescht and o.stand == stand:
                    o.geloescht = True
                    o.entscheidungen = {}     # zurückgezogen: erneutes Einreichen beginnt von vorn
            z.staende.pop("%s|%s" % (e["firma"], stand or ""), None)
            continue

        o = alle.get(e["objekt"])
        if o is None:
            o = alle[e["objekt"]] = ObjektZustand(e["objekt"])

        if art in (ev.EINGEREICHT, ev.GEAENDERT, ev.GELOESCHT):
            if o.besitzer is None and art == ev.EINGEREICHT:
                o.besitzer = e["firma"]
                o.ersteller_rolle = e["rolle"]
            if o.besitzer != e["firma"]:
                z.ignoriert.append(e)
                continue
            if art == ev.GELOESCHT:
                o.geloescht = True
            else:
                o.daten = dict(e["daten"]["objekt"])
                if art == ev.EINGEREICHT:
                    o.geloescht = False
                    o.letzte_einreichung = ev.sortierschluessel(e)
                    runde = e["daten"].get("runde")
                    if runde and runde not in o.runden:
                        o.runden.append(runde)
                    if e["daten"].get("stand"):
                        o.stand = e["daten"]["stand"]
            o.verlauf.append(e)
        elif art == ev.STATUS:
            o.entscheidungen[e["rolle"]] = e
            o.verlauf.append(e)
        elif art == ev.NACHRICHT:
            o.verlauf.append(e)

    for oid, o in alle.items():
        if o.daten is not None and not o.geloescht:
            z.objekte[oid] = o
    return z
