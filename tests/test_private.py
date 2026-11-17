import asyncio
import os
import sqlite3

import pytest

from app import bays

TOKEN = "t" * 40


@pytest.fixture()
def private_db(tmp_path):
    path = tmp_path / "private.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE bays (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, borough TEXT NOT NULL,
            lat REAL NOT NULL, lng REAL NOT NULL, capacity TEXT, source TEXT NOT NULL, status TEXT NOT NULL,
            approximate INTEGER NOT NULL DEFAULT 0);
        CREATE VIRTUAL TABLE bays_rtree USING rtree(rowid, min_lat, max_lat, min_lng, max_lng);
    """)
    rows = [
        ("a", "Brixton Road", "Lambeth", 51.4620, -0.1150, "lambeth-mymap", "Active", 0),
        ("b", "Coldharbour Lane", "Lambeth", 51.4625, -0.1160, "lime-parking-vercel", "Active", 1),
        ("c", "Closed Street", "Lambeth", 51.4614, -0.1157, "lambeth-mymap", "Suspended", 0),
    ]
    for i, r in enumerate(rows, 1):
        db.execute("INSERT INTO bays (rowid,id,name,borough,lat,lng,capacity,source,status,approximate) VALUES (?,?,?,?,?,?,NULL,?,?,?)", (i, *r))
        db.execute("INSERT INTO bays_rtree VALUES (?,?,?,?,?)", (i, r[3], r[3], r[4], r[4]))
    db.commit()
    db.close()
    return path


def test_private_index_skips_inactive_and_flags_approximate(private_db):
    # Arrange
    index = bays.BayIndex(private_db, "test boroughs")
    # Act
    r = index.nearest(51.4613, -0.1156)
    # Assert
    names = [b["name"] for b in r["bays"]]
    assert "Closed Street" not in names
    assert names == ["Brixton Road", "Coldharbour Lane"]
    assert r["spoken"].splitlines()[1].endswith("approximate location")
    assert r["bays"][1]["approximate"] is True
    assert index.stats() == {"Lambeth": 2}


def test_public_index_has_no_private_columns():
    assert bays.PUBLIC.has("status") is False
    assert "approximate" not in bays.nearest(51.5308, -0.1238)["bays"][0]


async def _call(app, path):
    calls, sent = [], []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": path, "raw_path": path.encode(), "headers": [], "query_string": b""}
    await app(scope, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    return start["status"] if start else None


def _recorder(label, seen):
    async def app(scope, receive, send):
        seen.append((label, scope["path"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app.router = None
    return app


def test_dispatch_routes_token_paths_and_404s_everything_else(monkeypatch):
    from app.server import PrivateDispatch

    monkeypatch.setattr("app.server.Starlette", lambda lifespan=None: None)
    seen = []
    d = PrivateDispatch(_recorder("public", seen), _recorder("private", seen), TOKEN)

    assert asyncio.run(_call(d, f"/p/{TOKEN}/mcp")) == 200
    assert seen[-1] == ("private", "/mcp")
    assert asyncio.run(_call(d, "/mcp")) == 200
    assert seen[-1] == ("public", "/mcp")
    for bad in (f"/p/{TOKEN}x/mcp", "/p/wrong/mcp", f"/p/{TOKEN}", f"/p/{TOKEN}/other", "/p", "/p/", f"/p/{TOKEN}/mcp/x"):
        n = len(seen)
        assert asyncio.run(_call(d, bad)) == 404, bad
        assert len(seen) == n, bad


def test_dispatch_without_private_404s_token_paths(monkeypatch):
    from app.server import PrivateDispatch

    monkeypatch.setattr("app.server.Starlette", lambda lifespan=None: None)
    seen = []
    d = PrivateDispatch(_recorder("public", seen), None, "")
    assert asyncio.run(_call(d, f"/p/{TOKEN}/mcp")) == 404
    assert seen == []


def test_log_filter_redacts_token():
    import logging

    from app.server import RedactPrivatePaths

    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:0", "POST", f"/p/{TOKEN}/mcp", "1.1", 200), None)
    RedactPrivatePaths().filter(rec)
    assert TOKEN not in rec.getMessage() and "/p/***/mcp" in rec.getMessage()
