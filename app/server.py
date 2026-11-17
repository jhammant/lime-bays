"""London e-bike parking bay finder: a remote MCP server (Streamable HTTP at /mcp)."""

import os
import time
from collections import defaultdict, deque

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from app import bays

RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "60"))
TRUSTED_HOPS = int(os.environ.get("TRUSTED_HOPS", "1"))
LOG_FORWARDING = os.environ.get("LOG_FORWARDING") == "1"

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


def build_app():
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
        # Public, unauthenticated, read-only data: no DNS-rebinding risk worth the Host allowlist.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "Mcp-Protocol-Version"],
    )
    return RateLimit(app, RATE_LIMIT)


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), proxy_headers=False)
