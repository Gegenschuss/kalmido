"""2.95.0 B (#1932): the import of a per diem spreadsheet (one sheet = one person, a row = a trip: from, to, start, end,
place, occasion, per diem; cell comments = note and the split by country). Two steps like office/fixedimport.py: preview
(nothing stored) and import (every row checked again by travel.rk_trip_clean), plus the undo of an import.
Every route: office_gate + office_org with the admin of the office area (travel._ctx). (Filled by part B.)"""
from ..core.config import app  # noqa: F401
