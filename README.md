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
hlsite deploy . --on endor --slug limebays --access public
```

Rate limit: 60 requests a minute per client IP (in memory, `RATE_LIMIT_PER_MIN`).
