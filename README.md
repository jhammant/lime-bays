# London e-bike parking bays (remote MCP server)

Ask Claude "where can I park the bike?" while cycling in London. One tool, `nearest_bays(lat, lng)`, returns the
three closest council dockless bike hire bays as short spoken lines ("Pancras Road, 80 metres, north-east"), with
coordinates in the structured result.

- MCP over Streamable HTTP at `/mcp` (stateless, no auth), plus `GET /health` and `GET /` (what it is + attribution).
- Bundled data: Camden and the City of London (Open Government Licence). Sources: [SOURCES.md](SOURCES.md).
- Optionally serves a bigger bay index you mount yourself (see below).

## Run it yourself

```bash
uv venv .venv -p 3.12 && uv pip install -p .venv -r requirements.txt pytest
python3 -I scripts/build.py            # data/raw -> data/bays.sqlite (SQLite R*Tree)
PORT=18765 .venv/bin/python -m app.server
.venv/bin/python scripts/smoke.py http://127.0.0.1:18765/mcp
.venv/bin/python -m pytest -q tests
```

Or with Docker (the image builds the OGL index itself):

```bash
docker build -t lime-bays .
docker run -p 8000:8000 lime-bays      # -> http://localhost:8000/mcp
```

To use it from claude.ai, put it behind HTTPS on a host you control and add `https://<your-host>/mcp` under
Settings, Connectors, Add custom connector. Ship only committed files (for example `git archive HEAD`) so local
venvs or data files never reach the build context.

Rate limit: a sliding one-minute window per client IP (in memory; `RATE_LIMIT_PER_MIN`, 300 in the image). The
client IP is taken `TRUSTED_HOPS` (default 1) entries from the right of `X-Forwarded-For`; if your proxy forwards
only its own address, every caller shares one bucket.

## Licence

The code is MIT (see `LICENSE`). The bay data in `data/raw/` is not: it contains public sector information licensed
under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
(London Borough of Camden; City of London Corporation). Sources and attribution are in `SOURCES.md`.

## A bigger index of your own

You can mount a second SQLite index with the same `bays` + `bays_rtree` tables (extra columns `status` and
`approximate` are honoured: only `Active` bays are returned, approximate ones are flagged in speech). Keep it out of
this repo and out of the image; mount it read-only, for example `-v /srv/bays:/private:ro`.

| Variable | Effect |
| --- | --- |
| `PRIVATE_DB_PATH` | Path to the mounted index (the image sets `/private/bays_private.sqlite`). |
| `PUBLIC_DATASET` | `ogl` (default): the main `/mcp` serves only the bundled OGL data. `full`: the main `/mcp` serves the mounted index, and its tool description says which boroughs it covers. If the file is missing it falls back to `ogl`. |
| `LIMEBAYS_PRIVATE_TOKEN` | At least 32 random URL-safe characters: also serves the mounted index at `/p/<token>/mcp` (constant-time token check; any other `/p/...` is a plain 404; access logs show `/p/***`). |

Only use `full` for data you are allowed to serve. When it is on, `/` keeps the OGL attribution for the Camden and
City of London records.
