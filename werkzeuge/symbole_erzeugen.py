# -*- coding: utf-8 -*-
"""Erzeugt die Symbole für den pyRevit-Reiter „DBK“ (icon.png und icon.dark.png je Knopf).

    py werkzeuge/symbole_erzeugen.py

Gemeinsames Motiv: Wand (grau) mit Durchbruch (orange). Gezeichnet in 4-facher
Größe und verkleinert, damit die Kanten glatt werden.
"""
import os

from PIL import Image, ImageDraw

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(WURZEL, "pyrevit", "DBK.extension", "DBK.tab", "Koordination.panel")

GROESSE = 96
S = 4                      # Überabtastung
N = GROESSE * S

ORANGE = (239, 159, 39, 255)
ORANGE_D = (186, 117, 23, 255)
BLAU = (24, 95, 165, 255)
GRUEN = (59, 109, 17, 255)
GRUEN_H = (99, 153, 34, 255)
WEISS = (255, 255, 255, 255)


def farben(dunkel):
    if dunkel:
        return {"wand": (180, 178, 169, 255), "wand_d": (136, 135, 128, 255), "linie": (211, 209, 199, 255),
                "blau": (133, 183, 235, 255), "papier": (68, 68, 65, 255)}
    return {"wand": (180, 178, 169, 255), "wand_d": (95, 94, 90, 255), "linie": (68, 68, 65, 255),
            "blau": BLAU, "papier": WEISS}


def p(*werte):
    """Koordinaten im 96er-Raster -> Zeichenraster."""
    return [v * S for v in werte]


def wand(d, f, x0, y0, x1, y1, loch=None):
    d.rounded_rectangle(p(x0, y0, x1, y1), radius=3 * S, fill=f["wand"], outline=f["wand_d"], width=2 * S)
    for y in range(y0 + 10, y1, 10):
        d.line(p(x0 + 2, y, x1 - 2, y), fill=f["wand_d"], width=S)
    if loch:
        lx0, ly0, lx1, ly1 = loch
        d.rectangle(p(lx0, ly0, lx1, ly1), fill=ORANGE, outline=ORANGE_D, width=2 * S)


def badge(d, cx, cy, r, farbe):
    d.ellipse(p(cx - r, cy - r, cx + r, cy + r), fill=farbe, outline=WEISS, width=3 * S)


def haken(d, cx, cy, r, breite=5):
    d.line(p(cx - r * 0.45, cy, cx - r * 0.1, cy + r * 0.38, cx + r * 0.5, cy - r * 0.35),
           fill=WEISS, width=breite * S, joint="curve")


def pfeil_hoch(d, cx, y_oben, y_unten, farbe, breite=7):
    d.line(p(cx, y_unten, cx, y_oben + 8), fill=farbe, width=breite * S)
    d.polygon(p(cx - 13, y_oben + 14, cx, y_oben, cx + 13, y_oben + 14), fill=farbe)


# ------------------------------------------------------------------ Symbole

def anmelden(d, f):
    d.ellipse(p(30, 8, 62, 40), fill=f["blau"])
    d.pieslice(p(14, 46, 78, 110), 180, 360, fill=f["blau"])
    badge(d, 70, 70, 17, GRUEN_H)
    haken(d, 70, 70, 17)


def pruefset(d, f):
    zeilen = [(10, 12, True), (24, 38, True), (24, 64, False)]
    d.line(p(18, 28, 18, 72), fill=f["linie"], width=2 * S)
    d.line(p(18, 46, 24, 46), fill=f["linie"], width=2 * S)
    d.line(p(18, 72, 24, 72), fill=f["linie"], width=2 * S)
    for x, y, an in zeilen:
        d.rounded_rectangle(p(x, y, x + 18, y + 18), radius=3 * S, fill=GRUEN if an else f["papier"],
                            outline=GRUEN if an else f["linie"], width=2 * S)
        if an:
            haken(d, x + 9, y + 9, 12, 4)
        d.rounded_rectangle(p(x + 26, y + 5, 88, y + 13), radius=3 * S, fill=f["wand"])
    d.rectangle(p(66, 64, 86, 84), fill=ORANGE, outline=ORANGE_D, width=2 * S)


def einreichen(d, f):
    wand(d, f, 8, 28, 62, 88, loch=(22, 46, 46, 66))
    pfeil_hoch(d, 74, 6, 60, f["blau"])
    d.line(p(46, 56, 74, 56), fill=f["blau"], width=7 * S)


def pruef_manager(d, f):
    wand(d, f, 8, 12, 72, 80, loch=(26, 32, 54, 56))
    d.rectangle(p(18, 24, 62, 64), outline=f["blau"], width=2 * S)
    badge(d, 70, 72, 19, GRUEN_H)
    haken(d, 70, 72, 19)


def modell(d, f):
    oben = [(48, 10), (82, 28), (48, 46), (14, 28)]
    links = [(14, 28), (48, 46), (48, 86), (14, 68)]
    rechts = [(48, 46), (82, 28), (82, 68), (48, 86)]
    d.polygon([v * S for pt in links for v in pt], fill=f["wand"], outline=f["wand_d"])
    d.polygon([v * S for pt in rechts for v in pt], fill=f["wand_d"], outline=f["wand_d"])
    d.polygon([v * S for pt in oben for v in pt], fill=(211, 209, 199, 255), outline=f["wand_d"])
    d.polygon([v * S for pt in [(24, 46), (38, 54), (38, 66), (24, 58)] for v in pt], fill=ORANGE, outline=ORANGE_D)
    badge(d, 74, 74, 17, f["blau"])
    d.line(p(74, 82, 74, 68), fill=WEISS, width=4 * S)
    d.polygon(p(67, 72, 74, 64, 81, 72), fill=WEISS)


def viewer(d, f):
    d.rounded_rectangle(p(6, 12, 90, 84), radius=6 * S, fill=f["papier"], outline=f["blau"], width=4 * S)
    d.rectangle(p(8, 14, 88, 26), fill=f["blau"])
    for x in (15, 23, 31):
        d.ellipse(p(x - 2.5, 17.5, x + 2.5, 22.5), fill=WEISS)
    d.ellipse(p(26, 36, 70, 76), outline=f["blau"], width=4 * S)
    d.ellipse(p(40, 48, 56, 64), fill=ORANGE)


# Ein Knopf im Menüband; die übrigen Zeichnungen bleiben als Vorrat für spätere Knöpfe.
SYMBOLE = {
    "Koordination": pruef_manager,
    "Modelle": modell,
}


def zeichnen(funktion, dunkel):
    bild = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    funktion(ImageDraw.Draw(bild), farben(dunkel))
    return bild.resize((GROESSE, GROESSE), Image.LANCZOS)


def main():
    vorschau = Image.new("RGBA", (len(SYMBOLE) * 110 + 10, 230), (250, 250, 248, 255))
    dunkel_bg = Image.new("RGBA", (len(SYMBOLE) * 110 + 10, 115), (59, 68, 83, 255))
    vorschau.paste(dunkel_bg, (0, 115))
    for i, (name, funktion) in enumerate(SYMBOLE.items()):
        ordner = os.path.join(PANEL, name + ".pushbutton")
        hell, dunkel = zeichnen(funktion, False), zeichnen(funktion, True)
        hell.save(os.path.join(ordner, "icon.png"))
        dunkel.save(os.path.join(ordner, "icon.dark.png"))
        vorschau.alpha_composite(hell, (10 + i * 110, 10))
        vorschau.alpha_composite(dunkel, (10 + i * 110, 125))
    ziel = os.path.join(WURZEL, "pyrevit", "symbole_vorschau.png")
    vorschau.save(ziel)
    print(ziel)


if __name__ == "__main__":
    main()
