# -*- coding: utf-8 -*-
"""Zeitstempel in UTC, damit Rechner in verschiedenen Zeitzonen vergleichbar sind."""
from __future__ import unicode_literals

import datetime


def jetzt_iso():
    """Aktuelle Zeit als ISO-8601 in UTC mit Millisekunden, z. B. 2026-11-24T10:20:11.123Z."""
    d = datetime.datetime.utcnow()
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def kompakt(iso):
    """ISO-Zeit ohne Trennzeichen, für Dateinamen: 20261124T102011123Z."""
    return iso.replace("-", "").replace(":", "").replace(".", "")
