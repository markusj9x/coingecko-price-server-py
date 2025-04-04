import asyncio
from fastapi import FastAPI, Request, Response as FastAPIResponse, HTTPException
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.sse import SseServerTransport
import requests
import logging
import os
import uvicorn
from pydantic import BaseModel, Field
from typing import ClassVar
# Import Starlette components for direct SSE handling
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import Response as StarletteResponse # Avoid name clash

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Pydantic Models for Tool Input ---
class CoinGeckoPriceInput(BaseModel):
    token_id: str = Field(..., description="The CoinGecko ID of the token (e.g., 'bitcoin', 'ethereum').")

# --- CoinGecko API Logic ---
async def get_coingecko_price_logic(token_id: str) -> dict:
    # ... (Keep the same async logic function as before)
    if not token_id or not isinstance(token_id, str):
        logger.error("Invalid token_id provided.")
        raise ValueError("Invalid or missing token_id parameter.")
    api_url = "https://api.coingecko.com/api/v3/simple/price"
    params = {'ids': token_id, 'vs_currencies': 'usd'}
    try:
        logger.info(f"Querying CoinGecko API for token: {token_id}")
        response = await asyncio.to_thread(requests.get, api_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and token_id in data and 'usd' in data[token_id]:
            price = data[token_id]['usd']
            logger.info(f"Successfully fetched price for {token_id}: ${price}")
            return {"content": [{"type": "text", "text": f"The current price of {token_id} is ${price} USD."}]}
        else:
            logger.warning(f"Could not find price data for token ID: {token_id} in response: {data}")
            raise ValueError(f"Could not find price data for token ID: {token_id}")
    except requests.exceptions.RequestException as e:
        logger.error(f"CoinGecko API request failed: {e}")
        raise ConnectionError(f"CoinGecko API request failed: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise RuntimeError(f"An unexpected error occurred: {e}")

# --- MCP Server Setup ---
# Define the tool structure manually for listTools response
coingecko_tool_definition = {
    "name": "get_coingecko_price",
    "description": "Get the current price of a cryptocurrency from CoinGecko using its ID.",
    "inputSchema": CoinGeckoPriceInput.model_json_schema()
}

# Create the core MCP Server instance
mcp_server = MCPServer(
    name="coingecko-price-server-py-sse",
    version="1.2.0"
)

# Register tool handlers using decorators on the MCPServer instance
@mcp_server.list_tools()
async def list_tools():
    logger.info("Handling listTools request")
    return [coingecko_tool_definition]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Handling callTool request for tool: {name}")
    if name == "get_coingecko_price":
        try:
            validated_input = CoinGeckoPriceInput(**arguments)
            return await get_coingecko_price_logic(validated_input.token_id)
        except Exception as e:
            logger.error(f"Error during tool execution for {name}: {e}")
            raise
    else:
        logger.error(f"Unknown tool called: {name}")
        raise ValueError(f"Unknown tool: {name}")

# --- SSE Transport and Starlette App Setup ---
# Initialize the SSE transport, specifying the path for POST messages
# This instance will be shared across connections in this simple setup
sse_transport = SseServerTransport("/messages/")
logger.info("SseServerTransport initialized for /messages/")

async def handle_sse_endpoint(scope, receive, send):
    """
    Handles incoming GET requests to establish the SSE stream using Starlette directly.
    Connects the MCP server logic to the transport for this connection.
    """
    logger.info(f"Incoming SSE connection request (Scope: {scope.get('path')})")
    # Use the transport's connect_sse method with low-level ASGI args
    try:
        async with sse_transport.connect_sse(scope, receive, send) as streams:
            logger.info("SSE stream connected via transport.connect_sse. Running MCP server logic.")
            # Run the MCP server logic, connecting it to the streams provided by the transport
            await mcp_server.run(streams, streams) # Pass streams for input and output
            logger.info("MCP server run loop finished for this SSE connection.")
    except asyncio.CancelledError:
        logger.info("SSE connection cancelled/closed by client.")
    except Exception as e:
        logger.error(f"Error during SSE handling: {e}", exc_info=True)
    finally:
        logger.info("SSE connection handler finished.")
        # Note: Transport cleanup might be handled internally by connect_sse context manager

# Create a Starlette app specifically for the SSE routes
sse_routes = [
    Route("/sse/", endpoint=handle_sse_endpoint), # GET endpoint for SSE stream
    Mount("/messages/", app=sse_transport.handle_post_message) # POST endpoint for client messages
]
sse_app = Starlette(routes=sse_routes)

# --- FastAPI App Setup ---
# Create the main FastAPI application instance
app = FastAPI(title="CoinGecko Price MCP Server (FastAPI/SSE)", version="1.2.0")

# Mount the Starlette SSE app onto the main FastAPI app
# Requests to /sse/ and /messages/ will now be handled by sse_app
app.mount("/", sse_app)

# Basic root endpoint on FastAPI for info
@app.get("/info", tags=["General"]) # Use a different path to avoid conflict with sse_app mount
async def root():
    return {
        "message": "CoinGecko Price MCP Server is running.",
        "sse_endpoint": "/sse/",
        "message_endpoint": "/messages/"
        }

# --- Main Execution ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000)) # Revert default port back for Render
    logger.info(f"Starting FastAPI server with Uvicorn on port {port}")
    # Use uvicorn to run the FastAPI app (which now includes the mounted SSE Starlette app)
    uvicorn.run(app, host="0.0.0.0", port=port)