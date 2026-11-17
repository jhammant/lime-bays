# London e-bike parking bays (remote MCP server)

Ask Claude "where can I park the bike?" while cycling in London. One tool, `nearest_bays(lat, lng)`, returns the
three closest council dockless bike hire bays as short spoken lines ("Pancras Road, 80 metres, north-east"), with
coordinates in the structured result.

- Endpoint: `https://limebays.hammantlabs.com/mcp` (Streamable HTTP, stateless, no auth). Add it in claude.ai
  under Settings, Connectors, Add custom connector.
- `GET /health`, `GET /` (what it is + attribution).
- Coverage: Camden and the City of London. Sources and licences: [SOURCES.md](SOURCES.md).

```bash
uv venv .venv -p 3.12 && uv pip install -p .venv -r requirements.txt pytest
python3 -I scripts/build.py            # data/raw -> data/bays.sqlite (SQLite R*Tree)
PORT=18765 .venv/bin/python -m app.server
.venv/bin/python scripts/smoke.py http://127.0.0.1:18765/mcp
.venv/bin/python -m pytest -q tests
scripts/deploy_endor.sh                # ships git HEAD only, via hlsite/loom
```

Rate limit: a sliding one-minute window per client IP (in memory; `RATE_LIMIT_PER_MIN`, 300 in the image).
The client IP is taken `TRUSTED_HOPS` (default 1) entries from the right of `X-Forwarded-For`. Behind endor's
edge today every request arrives as the edge's own address (10.0.0.184, no client IP forwarded), so in
practice the limit is one shared bucket for everyone until the edge forwards the real client IP.

## Licence

The code is MIT (see `LICENSE`). The bay data in `data/raw/` is not: it contains public sector information licensed
under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
(London Borough of Camden; City of London Corporation). Sources and attribution are in `SOURCES.md`.

## Optional private index

The server can also serve a second, private bay index (for example one you compiled yourself from sources you
may use but not republish). It is off unless both are set:

- `PRIVATE_DB_PATH`: a SQLite file with the same `bays` + `bays_rtree` tables (extra columns `status` and
  `approximate` are honoured: only `Active` bays are returned, approximate ones are flagged in speech).
- `LIMEBAYS_PRIVATE_TOKEN`: at least 32 random URL-safe characters.

It is then served only at `/p/<token>/mcp` (constant-time token check; any other `/p/...` is a plain 404, and
access logs show `/p/***`). The public `/mcp` is unaffected. Keep the private file out of this repo and out of
the image: mount it read-only (see `scripts/deploy_endor.sh`).
