"""MCP Server exposing the automotive knowledge base via SSE transport.

Runs on port 8002 and provides tools for DTC lookup, semantic search,
code listing, and system statistics.
"""
import sys
import json

sys.path.insert(0, "/app")

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse

from tools import lookup_dtc, search_knowledge, list_dtc_codes, get_system_stats

# Create MCP server
mcp_server = Server("automotive-knowledge-base")


@mcp_server.list_tools()
async def handle_list_tools():
    """Return the list of available MCP tools."""
    return [
        Tool(
            name="lookup_dtc",
            description="Look up full details for a specific automotive DTC "
                       "(Diagnostic Trouble Code) including causes, diagnostic "
                       "steps, related sensors, and TSB references.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "DTC code (e.g., 'P0301', 'B0100', 'C0035')"
                    }
                },
                "required": ["code"]
            }
        ),
        Tool(
            name="search_knowledge",
            description="Semantic vector search across the automotive knowledge "
                       "base. Use natural language queries to find relevant "
                       "diagnostic information.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                        "default": 10
                    },
                    "min_trust": {
                        "type": "number",
                        "description": "Minimum trust score filter (0-1)",
                        "default": 0.0
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="list_dtc_codes",
            description="List available DTC codes with optional filtering by "
                       "category and confidence score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter by category (e.g., 'Powertrain')"
                    },
                    "min_confidence": {
                        "type": "number",
                        "description": "Minimum confidence score (0-1)",
                        "default": 0.0
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 50)",
                        "default": 50
                    }
                }
            }
        ),
        Tool(
            name="get_system_stats",
            description="Get knowledge base coverage and quality metrics "
                       "including total codes, documents, confidence scores, "
                       "and category breakdowns.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


@mcp_server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    """Handle MCP tool calls."""
    try:
        if name == "lookup_dtc":
            result = lookup_dtc(arguments["code"])
        elif name == "search_knowledge":
            result = search_knowledge(
                arguments["query"],
                limit=arguments.get("limit", 10),
                min_trust=arguments.get("min_trust", 0.0),
            )
        elif name == "list_dtc_codes":
            result = list_dtc_codes(
                category=arguments.get("category"),
                min_confidence=arguments.get("min_confidence", 0.0),
                limit=arguments.get("limit", 50),
            )
        elif name == "get_system_stats":
            result = get_system_stats()
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2, default=str)
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"error": str(e)})
        )]


# Health check endpoint
async def health(request):
    return JSONResponse({"status": "running", "service": "mcp-server"})


# Set up SSE transport
sse = SseServerTransport("/messages/")

async def handle_sse(request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0], streams[1], mcp_server.create_initialization_options()
        )


# Build Starlette app
app = Starlette(
    routes=[
        Route("/health", health),
        Route("/sse", handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ]
)


if __name__ == "__main__":
    import uvicorn
    print("[mcp-server] Starting on port 8002...")
    uvicorn.run(app, host="0.0.0.0", port=8002)
