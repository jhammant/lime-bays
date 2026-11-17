#!/usr/bin/env python3
"""Build data/bays.sqlite (bays table + R*Tree index) from the raw council files in data/raw/.

Usage: python3 -I scripts/build.py [raw_dir] [out_path]
"""

import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "raw"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "bays.sqlite"

DEDUPE_METRES = 15  # City layers overlap; treat bays this close as the same bay


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def centroid(geom):
    """Mean of the vertices: good enough for bays a few metres long."""
    pts = []

    def walk(c):
        if isinstance(c[0], (int, float)):
            pts.append(c)
        else:
            for x in c:
                walk(x)

    walk(geom["coordinates"])
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def tidy(name):
    name = " ".join(str(name or "").split())
    return name if name and name.upper() not in {"N/A", "NONE", "NULL"} else ""


def load_camden():
    rows = json.loads((RAW / "camden.json").read_text())
    for r in rows:
        if r.get("restriction_type") != "dockless bike hire":
            continue
        yield {
            "id": f"camden-{r['unique_identifier']}",
            "name": tidy(r.get("road_name")),
            "borough": "Camden",
            "lat": float(r["latitude"]),
            "lng": float(r["longitude"]),
            "capacity": r.get("parking_spaces"),
            "source": "camden-parking-bays",
        }


def load_city():
    layers = [
        # (layer, name field, id field, filter)
        (8, "STREET_NAM", "OBJECTID", lambda p: "SUSPENDED" not in str(p.get("BAY_TYPE", "")).upper()),
        (29, "LOCATION", "OBJECTID", lambda p: str(p.get("STATUS", "")).lower() == "live"),
        (21, "STREET_NAME", "OBJECTID", lambda p: True),
    ]
    out = []
    for layer, name_field, id_field, keep in layers:
        fc = json.loads((RAW / f"city_layer{layer}.geojson").read_text())
        for f in fc["features"]:
            p = f["properties"]
            if not f.get("geometry") or not keep(p):
                continue
            lat, lng = centroid(f["geometry"])
            if any(haversine_m(lat, lng, b["lat"], b["lng"]) < DEDUPE_METRES for b in out):
                continue
            out.append({
                "id": f"city-{layer}-{p[id_field]}",
                "name": tidy(p.get(name_field)),
                "borough": "City of London",
                "lat": lat,
                "lng": lng,
                "capacity": p.get("CAPCITY") or p.get("NUMBER_OF_BAYS"),
                "source": f"city-of-london-compass-layer-{layer}",
            })
    return out


def fill_missing_names(bays):
    """Cheap fallback: borrow the name of the nearest bay that has one."""
    named = [b for b in bays if b["name"]]
    for b in bays:
        if not b["name"]:
            near = min(named, key=lambda n: haversine_m(b["lat"], b["lng"], n["lat"], n["lng"]))
            b["name"] = f"near {near['name']}"


def main():
    bays = list(load_camden()) + load_city()
    fill_missing_names(bays)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript("""
        CREATE TABLE bays (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                           borough TEXT NOT NULL, lat REAL NOT NULL, lng REAL NOT NULL,
                           capacity TEXT, source TEXT NOT NULL);
        CREATE VIRTUAL TABLE bays_rtree USING rtree(rowid, min_lat, max_lat, min_lng, max_lng);
    """)
    for b in bays:
        cur = db.execute(
            "INSERT INTO bays (id, name, borough, lat, lng, capacity, source) VALUES (?,?,?,?,?,?,?)",
            (b["id"], b["name"], b["borough"], b["lat"], b["lng"],
             None if b["capacity"] is None else str(b["capacity"]), b["source"]),
        )
        db.execute("INSERT INTO bays_rtree VALUES (?,?,?,?,?)", (cur.lastrowid, b["lat"], b["lat"], b["lng"], b["lng"]))
    db.commit()
    db.close()
    tmp.replace(OUT)
    counts = {}
    for b in bays:
        counts[b["borough"]] = counts.get(b["borough"], 0) + 1
    print(f"wrote {OUT} with {len(bays)} bays: {counts}")


if __name__ == "__main__":
    main()
