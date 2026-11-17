#!/usr/bin/env python3
"""Smoke test with the official MCP SDK client: python scripts/smoke.py [http://host/mcp]"""

import asyncio
import sys

from mcp import Client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18765/mcp"
POINTS = {
    "St Pancras": (51.5308, -0.1238),
    "Camden Town tube": (51.5392, -0.1426),
    "Bank": (51.5133, -0.0890),
    "Brixton": (51.4613, -0.1156),
    "Hackney Central": (51.5469, -0.0553),
    "Westminster / Soho": (51.5136, -0.1365),
    "Derby": (52.9225, -1.4746),
    "Richmond (London, no coverage)": (51.4613, -0.3037),
}


async def main():
    async with Client(URL) as client:
        tools = await client.list_tools()
        print("tools:", [t.name for t in tools.tools])
        for label, (lat, lng) in POINTS.items():
            res = await client.call_tool("nearest_bays", {"lat": lat, "lng": lng})
            text = res.content[0].text
            sc = res.structured_content or {}
            print(f"\n## {label}: status={sc.get('status')} bays={len(sc.get('bays', []))} error={res.is_error}")
            print(text)
            if sc.get("bays"):
                print("   ", [(b["borough"], b.get("source")) for b in sc["bays"]])


asyncio.run(main())
