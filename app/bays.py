"""Nearest-bay lookup and speech formatting (no MCP here, so it is easy to test)."""

import math
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("BAYS_DB", Path(__file__).resolve().parent.parent / "data" / "bays.sqlite"))

SEARCH_RADIUS_M = 2000
RESULTS = 3
# Rough Greater London box (the M25 sits just outside it).
LONDON = {"min_lat": 51.28, "max_lat": 51.70, "min_lng": -0.52, "max_lng": 0.34}
COVERAGE = "Camden and the City of London"

ATTRIBUTION = (
    "Contains public sector information licensed under the Open Government Licence v3.0 "
    "(London Borough of Camden; City of London Corporation)."
)

COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(deg):
    return COMPASS[int((deg + 22.5) // 45) % 8]


def spoken_distance(m):
    """To 10 m under 200 m, to 50 m up to 1 km, then km to one decimal."""
    if m < 200:
        return f"{max(10, int(round(m / 10.0)) * 10)} metres"
    if m < 1000:
        r = int(round(m / 50.0)) * 50
        return "1 kilometre" if r >= 1000 else f"{r} metres"
    km = round(m / 1000.0, 1)
    return f"{km:g} kilometre" + ("" if km == 1 else "s")


def in_london(lat, lng):
    return LONDON["min_lat"] <= lat <= LONDON["max_lat"] and LONDON["min_lng"] <= lng <= LONDON["max_lng"]


def _connect():
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


_DB = None


def db():
    global _DB
    if _DB is None:
        _DB = _connect()
    return _DB


def stats():
    rows = db().execute("SELECT borough, COUNT(*) AS n FROM bays GROUP BY borough ORDER BY borough").fetchall()
    return {r["borough"]: r["n"] for r in rows}


def nearest(lat, lng, k=RESULTS, radius_m=SEARCH_RADIUS_M):
    """Return {status, spoken, bays}. status: ok | outside_london | none_nearby | invalid."""
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or math.isnan(lat) or math.isnan(lng):
        return {"status": "invalid", "spoken": "That location doesn't look valid. Please send latitude and longitude in decimal degrees.", "bays": []}
    if not in_london(lat, lng):
        return {
            "status": "outside_london",
            "spoken": f"That location is outside London. I only know e-bike parking bays in {COVERAGE}.",
            "bays": [],
        }
    dlat = radius_m / 111_320.0
    dlng = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    rows = db().execute(
        """SELECT b.id, b.name, b.borough, b.lat, b.lng, b.capacity FROM bays_rtree r JOIN bays b ON b.rowid = r.rowid
           WHERE r.min_lat >= ? AND r.max_lat <= ? AND r.min_lng >= ? AND r.max_lng <= ?""",
        (lat - dlat, lat + dlat, lng - dlng, lng + dlng),
    ).fetchall()
    found = []
    for r in rows:
        d = haversine_m(lat, lng, r["lat"], r["lng"])
        if d <= radius_m:
            found.append((d, r))
    found.sort(key=lambda x: x[0])
    if not found:
        return {
            "status": "none_nearby",
            "spoken": f"No parking bays within 2 kilometres in my data. I only cover {COVERAGE} so far, so check the Lime app.",
            "bays": [],
        }
    bays, lines = [], []
    for d, r in found[:k]:
        direction = compass(bearing_deg(lat, lng, r["lat"], r["lng"]))
        dist = spoken_distance(d)
        lines.append(f"{r['name']}, {dist}, {direction}")
        bays.append({
            "name": r["name"],
            "borough": r["borough"],
            "distance_m": round(d),
            "distance_spoken": dist,
            "direction": direction,
            "lat": round(r["lat"], 6),
            "lng": round(r["lng"], 6),
            "id": r["id"],
            "capacity": r["capacity"],
        })
    return {"status": "ok", "spoken": "\n".join(lines), "bays": bays}
