"""London e-bike parking bay finder: a remote MCP server (Streamable HTTP at /mcp)."""

import contextlib
import hashlib
import hmac
import logging
import os
import re
import time
from collections import defaultdict, deque

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from app import bays

RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "60"))
TRUSTED_HOPS = int(os.environ.get("TRUSTED_HOPS", "1"))
LOG_FORWARDING = os.environ.get("LOG_FORWARDING") == "1"
# Optional private index, served only at /p/<token>/mcp. Both must be set (and the file present) to turn it on.
PRIVATE_DB_PATH = os.environ.get("PRIVATE_DB_PATH", "")
PRIVATE_TOKEN = os.environ.get("LIMEBAYS_PRIVATE_TOKEN", "")
MIN_TOKEN_LEN = 32

INSTRUCTIONS = (
    "Finds the nearest dockless e-bike parking bays (Lime, Forest, Voi) in London for someone who is cycling. "
    "Answers are short spoken directions, meant to be read aloud. Coverage so far: "
    f"{bays.COVERAGE}. {bays.ATTRIBUTION}"
)

mcp = MCPServer(name="london-ebike-bays", title="London e-bike parking bays", instructions=INSTRUCTIONS, version="0.1.0")


@mcp.tool(
    name="nearest_bays",
    title="Nearest e-bike parking bays",
    description=(
        "Find the three closest council e-bike / dockless bike hire parking bays (where Lime, Forest and Voi bikes "
        "must be left) to a point in London. Use the user's current location: if you have device location, use it; "
        "otherwise ask the user where they are and turn a place name, station or street into approximate latitude "
        "and longitude yourself before calling. Returns one line per bay for reading aloud, e.g. "
        "'Pancras Road, 80 metres, north-east' (direction is from the user to the bay), plus structured "
        f"coordinates for maps. Searches up to 2 km. Coverage: {bays.COVERAGE} only for now. {bays.ATTRIBUTION}"
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def nearest_bays(lat: float, lng: float) -> CallToolResult:
    """lat: latitude of the user in decimal degrees (WGS84), e.g. 51.5308. lng: longitude in decimal degrees, e.g. -0.1238."""
    result = bays.nearest(lat, lng)
    return CallToolResult(
        content=[TextContent(type="text", text=result["spoken"])],
        structured_content={**result, "attribution": bays.ATTRIBUTION},
    )


PRIVATE_COVERAGE = (
    "every London borough that publishes its bay locations: Brent, Camden, City of London, Ealing, Greenwich, "
    "Hackney, Haringey, Islington, Kensington and Chelsea, Lambeth, Lewisham, Merton, Southwark, Wandsworth "
    "and Westminster"
)
PRIVATE_NOTE = (
    "Bay locations come from council publications (open data, council bay maps, traffic orders) gathered for "
    "private personal use; most of them state no licence. Some bays were geocoded from traffic-order text and are "
    "marked approximate."
)


def build_private_mcp(index):
    server = MCPServer(
        name="london-ebike-bays-all",
        title="London e-bike parking bays (all boroughs)",
        instructions=(
            "Finds the nearest dockless e-bike parking bays (Lime, Forest, Voi) in London for someone who is cycling. "
            f"Answers are short spoken directions, meant to be read aloud. Coverage: {PRIVATE_COVERAGE}. {PRIVATE_NOTE}"
        ),
        version="0.2.0",
    )

    @server.tool(
        name="nearest_bays",
        title="Nearest e-bike parking bays",
        description=(
            "Find the three closest e-bike / dockless bike hire parking bays (where Lime, Forest and Voi bikes must be "
            "left) to a point in London. Use the user's current location: if you have device location, use it; "
            "otherwise ask the user where they are and turn a place name, station or street into approximate latitude "
            "and longitude yourself before calling. Returns one line per bay for reading aloud, e.g. "
            "'Pancras Road, 80 metres, north-east' (direction is from the user to the bay; 'approximate location' "
            "means the council only published a street description), plus structured coordinates for maps. "
            f"Searches up to 2 km. Coverage: {PRIVATE_COVERAGE}. {PRIVATE_NOTE}"
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    )
    def nearest_bays(lat: float, lng: float) -> CallToolResult:
        """lat: latitude of the user in decimal degrees (WGS84), e.g. 51.5308. lng: longitude in decimal degrees, e.g. -0.1238."""
        result = index.nearest(lat, lng)
        return CallToolResult(
            content=[TextContent(type="text", text=result["spoken"])],
            structured_content={**result, "sources": PRIVATE_NOTE},
        )

    return server


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def health(_: Request):
    return JSONResponse({"ok": True, "bays": bays.stats()})


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def root(_: Request):
    return PlainTextResponse(
        "London e-bike parking bay finder: a remote MCP server at /mcp (tool: nearest_bays). " + bays.ATTRIBUTION + "\n"
    )


class RateLimit:
    """Sliding one-minute window per client IP (in memory; one container)."""

    def __init__(self, app, per_minute):
        self.app, self.per_minute = app, per_minute
        self.hits = defaultdict(deque)
        self.last_sweep = time.monotonic()

    def client_ip(self, scope):
        """With TRUSTED_HOPS proxies in front, the client is that many X-Forwarded-For entries from the right.
        Entries further left are written by the client, so they are ignored (no spoofing past the limit)."""
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        if LOG_FORWARDING:
            print("forwarding:", {k: v for k, v in headers.items() if "forward" in k or "real-ip" in k}, scope.get("client"), flush=True)
        hops = [h.strip() for h in headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if TRUSTED_HOPS > 0 and hops:
            return hops[max(0, len(hops) - TRUSTED_HOPS)]
        return (scope.get("client") or ("?",))[0]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await self.app(scope, receive, send)
        now = time.monotonic()
        if now - self.last_sweep > 300:
            for ip in [ip for ip, q in self.hits.items() if not q or now - q[-1] > 60]:
                del self.hits[ip]
            self.last_sweep = now
        q = self.hits[self.client_ip(scope)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            resp = JSONResponse({"error": "rate limited, try again in a minute"}, status_code=429, headers={"Retry-After": "60"})
            return await resp(scope, receive, send)
        q.append(now)
        return await self.app(scope, receive, send)


def _mcp_app(server):
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
        # Read-only bay data, no auth cookies: no DNS-rebinding risk worth the Host allowlist.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "Mcp-Protocol-Version"],
    )
    return app


def _digest(s):
    return hashlib.sha256(s.encode()).digest()


class PrivateDispatch:
    """Public app for every path except /p/...; /p/<token>/mcp goes to the private app when the token matches
    (constant-time compare of SHA-256 digests). Any other /p/... is a plain 404, whether or not private is on."""

    def __init__(self, public, private=None, token=""):
        self.public, self.private = public, private
        self.token_digest = _digest(token) if private is not None else None
        apps = [a for a in (public, private) if a is not None]

        @contextlib.asynccontextmanager
        async def lifespan(_):
            async with contextlib.AsyncExitStack() as stack:
                for a in apps:
                    await stack.enter_async_context(a.router.lifespan_context(a))
                yield

        self.lifespan_app = Starlette(lifespan=lifespan)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.lifespan_app(scope, receive, send)
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/p" or path.startswith("/p/")):
            return await self.public(scope, receive, send)
        parts = path.split("/")  # ["", "p", token, "mcp", ...]
        ok = (
            self.private is not None
            and len(parts) in (4, 5)
            and parts[3] == "mcp"
            and (len(parts) == 4 or parts[4] == "")
            and hmac.compare_digest(_digest(parts[2]), self.token_digest)
        )
        if not ok:
            return await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
        inner = dict(scope, path="/mcp", raw_path=b"/mcp", root_path="")
        return await self.private(inner, receive, send)


class RedactPrivatePaths(logging.Filter):
    """Never let /p/<token>/... reach a log line."""

    pattern = re.compile(r"/p/[^/\s\"]+")

    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(self.pattern.sub("/p/***", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = self.pattern.sub("/p/***", record.msg)
        return True


for _name in ("uvicorn.access", "uvicorn.error", "mcp", "starlette"):
    logging.getLogger(_name).addFilter(RedactPrivatePaths())


def private_index():
    if not (PRIVATE_DB_PATH and PRIVATE_TOKEN):
        return None
    if len(PRIVATE_TOKEN) < MIN_TOKEN_LEN:
        print(f"private index disabled: LIMEBAYS_PRIVATE_TOKEN is shorter than {MIN_TOKEN_LEN} characters", flush=True)
        return None
    if not os.path.isfile(PRIVATE_DB_PATH):
        print("private index disabled: PRIVATE_DB_PATH is not a file", flush=True)
        return None
    index = bays.BayIndex(PRIVATE_DB_PATH, "the 15 London boroughs that publish their bay locations")
    print(f"private index on: {sum(index.stats().values())} active bays", flush=True)
    return index


def build_app():
    index = private_index()
    private = _mcp_app(build_private_mcp(index)) if index else None
    return RateLimit(PrivateDispatch(_mcp_app(mcp), private, PRIVATE_TOKEN), RATE_LIMIT)


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), proxy_headers=False)
