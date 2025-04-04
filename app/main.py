import asyncio
from fastapi import FastAPI, Request, Response, HTTPException
from mcp.server.lowlevel import Server as MCPServer
from mcp.server.sse import SseServerTransport
# Import specific types if possible, otherwise define manually or handle dynamically
# from mcp.types import Tool, TextContent # Example if types were available
import requests
import logging
import os
import uvicorn
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse # Needed for SSE
from starlette.routing import Route, Mount # Needed if using Starlette directly for SSE part

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
    version="1.2.0" # Incremented version
)

# Register tool handlers using decorators on the MCPServer instance
@mcp_server.list_tools()
async def list_tools():
    logger.info("Handling listTools request")
    # The SDK decorator likely handles formatting this into the full JSON-RPC response
    return [coingecko_tool_definition]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"Handling callTool request for tool: {name}")
    if name == "get_coingecko_price":
        try:
            validated_input = CoinGeckoPriceInput(**arguments)
            # The SDK decorator likely handles formatting this into the full JSON-RPC response
            return await get_coingecko_price_logic(validated_input.token_id)
        except Exception as e:
            logger.error(f"Error during tool execution for {name}: {e}")
            raise # Re-raise for the decorator to handle
    else:
        logger.error(f"Unknown tool called: {name}")
        # Raise an error that the SDK decorator can convert to MethodNotFound
        # Using a specific MCPError might be better if importable, otherwise ValueError
        raise ValueError(f"Unknown tool: {name}")

# --- FastAPI App Setup ---
app = FastAPI(title="CoinGecko Price MCP Server (FastAPI/SSE)", version="1.2.0")

# Store the active transport instance (simple approach for single client)
active_transport: SseServerTransport | None = None

# 1. SSE Endpoint (GET /sse) - Using Starlette's StreamingResponse via FastAPI
@app.get("/sse/") # Note the trailing slash
async def handle_sse_connection(request: Request):
    global active_transport
    logger.info(f"Incoming SSE connection request: {request.url}")

    # Create the SSE transport instance, specifying the path for POST messages
    transport = SseServerTransport("/messages/") # Path relative to root
    active_transport = transport # Store for the POST handler
    logger.info("SseServerTransport initialized for /messages/")

    async def event_stream():
        # Use the transport's connect_sse method as an async generator
        try:
            async with transport.connect_sse(request) as streams:
                logger.info("SSE stream connected via transport.connect_sse. Running MCP server logic.")
                # Run the MCP server logic, connecting it to the streams provided by the transport
                await mcp_server.run(streams, streams) # Pass streams for input and output
                logger.info("MCP server run loop finished for this SSE connection.")
        except asyncio.CancelledError:
            logger.info("SSE connection cancelled/closed by client.")
        except Exception as e:
            logger.error(f"Error during SSE streaming: {e}", exc_info=True)
        finally:
            logger.info("Cleaning up SSE connection.")
            # Clear the active transport when the connection closes
            # Check if it's still the same instance before clearing
            global active_transport
            if active_transport == transport:
                active_transport = None

    # Return a StreamingResponse, which FastAPI/Starlette handles correctly for SSE
    return StreamingResponse(event_stream(), media_type="text/event-stream")


# 2. Message Endpoint (POST /messages)
@app.post("/messages/") # Note the trailing slash
async def handle_post_message(request: Request):
    logger.info("Received POST /messages request")
    if active_transport and hasattr(active_transport, 'handle_post_message'):
        # Delegate the handling of the POST request to the active transport instance
        # The transport needs the raw Starlette request/response handling capability
        # This might require adapting how handle_post_message is called if it expects
        # Starlette's scope/receive/send directly instead of a FastAPI Request.
        # For now, assuming it can work with FastAPI's Request or we adapt later.
        logger.info("Delegating POST request to active SseServerTransport")
        # This part is tricky - SseServerTransport might expect Starlette's low-level ASGI interface.
        # We might need to wrap this differently or use Starlette directly as in Heurist example.
        # Let's try a simplified delegation first. If it fails, we'll need Starlette mounting.
        try:
            # Attempt direct delegation (might fail if transport expects ASGI scope/receive/send)
            # The transport's handle_post_message should ideally parse the body,
            # feed the request to mcp_server via its internal streams, and handle the response.
            # It might need to return a Starlette Response object.
            # This is the most uncertain part without exact SDK docs for handle_post_message.
            # Let's assume it handles the request and returns None or a response object.
             response = await active_transport.handle_post_message(request)
             if response:
                 return response
             else:
                 # If it handles internally and doesn't return a response object
                 return Response(status_code=202, content="Request processed via SSE")

        except Exception as e:
             logger.error(f"Error delegating POST to transport: {e}", exc_info=True)
             raise HTTPException(status_code=500, detail="Error processing message")

    else:
        logger.error("Received POST /messages but no active SSE transport or handle_post_message method found.")
        raise HTTPException(status_code=400, detail="No active SSE connection or transport cannot handle POST.")


# Basic root endpoint
@app.get("/")
def read_root():
    return {"message": "CoinGecko Price MCP Server (FastAPI/SSE) is running."}


# --- Main Execution ---
if __name__ == "__main__":
    # Changed default port to 8001 to avoid conflict
    port = int(os.getenv("PORT", 8001))
    logger.info(f"Starting FastAPI server with Uvicorn on port {port}")
    # Use uvicorn to run the FastAPI app
    uvicorn.run(app, host="0.0.0.0", port=port)