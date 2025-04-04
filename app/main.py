from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP
from .sse import create_sse_app # Import the function to create the SSE app
import requests # For making HTTP requests to CoinGecko
import logging
from pydantic import BaseModel, Field

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Pydantic Models for Tool Input ---
# Define input schema using Pydantic for automatic validation
class CoinGeckoPriceInput(BaseModel):
    token_id: str = Field(..., description="The CoinGecko ID of the token (e.g., 'bitcoin', 'ethereum').")

# --- CoinGecko API Logic ---
def get_coingecko_price_logic(token_id: str) -> dict:
    """
    Fetches the price from CoinGecko API.

    Args:
        token_id: The CoinGecko ID of the token.

    Returns:
        A dictionary containing the price or an error message.
    """
    if not token_id or not isinstance(token_id, str):
        logger.error("Invalid token_id provided.")
        # Raise exception for FastMCP to handle and convert to MCP error
        raise ValueError("Invalid or missing token_id parameter.")

    api_url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        'ids': token_id,
        'vs_currencies': 'usd'
    }
    try:
        logger.info(f"Querying CoinGecko API for token: {token_id}")
        response = requests.get(api_url, params=params, timeout=10) # Added timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()

        if data and token_id in data and 'usd' in data[token_id]:
            price = data[token_id]['usd']
            logger.info(f"Successfully fetched price for {token_id}: ${price}")
            # Return structure expected by MCP CallToolResponse 'content'
            return {
                "content": [{
                    "type": "text",
                    "text": f"The current price of {token_id} is ${price} USD."
                }]
            }
        else:
            logger.warning(f"Could not find price data for token ID: {token_id} in response: {data}")
            raise ValueError(f"Could not find price data for token ID: {token_id}")

    except requests.exceptions.RequestException as e:
        logger.error(f"CoinGecko API request failed: {e}")
        raise ConnectionError(f"CoinGecko API request failed: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise RuntimeError(f"An unexpected error occurred: {e}")


# --- FastAPI and MCP Setup ---
# Create the main FastAPI application instance
app = FastAPI(title="CoinGecko Price MCP Server", version="1.0.0")

# Create the FastMCP instance, associating it with the FastAPI app
# FastMCP automatically creates necessary MCP endpoints (like /mcp.json)
mcp = FastMCP(
    "coingecko-price-server-py", # Server name
    version="1.0.0",
    title="CoinGecko Price Server (Python/SSE)",
    description="Provides CoinGecko cryptocurrency prices via MCP SSE transport."
)

# Define the MCP tool using the @mcp.tool decorator
# FastMCP handles input validation using the Pydantic model (CoinGeckoPriceInput)
# and converts exceptions into appropriate MCP error responses.
@mcp.tool(input_model=CoinGeckoPriceInput)
def get_coingecko_price(input_data: CoinGeckoPriceInput) -> dict:
    """
    Get the current price of a cryptocurrency from CoinGecko using its ID.
    """
    logger.info(f"Executing tool 'get_coingecko_price' for token_id: {input_data.token_id}")
    # The logic function returns the structure needed for the 'result' field
    # of the MCP CallToolResponse. FastMCP wraps this correctly.
    return get_coingecko_price_logic(input_data.token_id)


# --- Mount SSE App ---
# Create the Starlette app that handles SSE transport using the function from sse.py
sse_app = create_sse_app(mcp)

# Mount the SSE Starlette app onto the main FastAPI app at the root path.
# Requests to /sse/ and /messages/ will be handled by the sse_app.
app.mount("/", sse_app)

# --- Optional: Add a simple root endpoint for basic info ---
@app.get("/info", tags=["General"])
async def root():
    return {
        "message": "CoinGecko Price MCP Server is running.",
        "mcp_spec": "/mcp.json",
        "sse_endpoint": "/sse/",
        "message_endpoint": "/messages/"
        }

# Note: To run this locally, use: uvicorn app.main:app --reload --port 8000
# The FastMCP instance automatically adds necessary MCP routes to the 'app'