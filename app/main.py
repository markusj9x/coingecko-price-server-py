import asyncio
from mcp.server.lowlevel import Server as MCPServer # Import from submodule and alias
from mcp.tool import Tool # Attempt import from submodule
import requests
import logging
import os
from pydantic import BaseModel, Field # Keep Pydantic for input validation

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Pydantic Models for Tool Input ---
class CoinGeckoPriceInput(BaseModel):
    token_id: str = Field(..., description="The CoinGecko ID of the token (e.g., 'bitcoin', 'ethereum').")

# --- CoinGecko API Logic ---
# Make this an async function as MCP tool execution might be async
async def get_coingecko_price_logic(token_id: str) -> dict:
    """
    Fetches the price from CoinGecko API asynchronously.

    Args:
        token_id: The CoinGecko ID of the token.

    Returns:
        A dictionary containing the price or an error message suitable for MCP response.
    """
    if not token_id or not isinstance(token_id, str):
        logger.error("Invalid token_id provided.")
        # Raise standard exceptions; MCPServer should handle converting them
        raise ValueError("Invalid or missing token_id parameter.")

    api_url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        'ids': token_id,
        'vs_currencies': 'usd'
    }
    try:
        logger.info(f"Querying CoinGecko API for token: {token_id}")
        # Use an async HTTP client if available and needed, or run sync requests
        # For simplicity here, using sync requests (consider httpx for async)
        response = await asyncio.to_thread(requests.get, api_url, params=params, timeout=10)
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


# --- Define MCP Tool Class ---
class CoinGeckoPriceTool(Tool):
    name = "get_coingecko_price"
    description = "Get the current price of a cryptocurrency from CoinGecko using its ID."
    input_model = CoinGeckoPriceInput # Use Pydantic model for validation

    async def execute(self, input_data: CoinGeckoPriceInput) -> dict:
        """
        Executes the tool logic.
        """
        logger.info(f"Executing tool '{self.name}' for token_id: {input_data.token_id}")
        # Call the async logic function
        # MCPServer will handle wrapping the result/exception into the MCP response format
        return await get_coingecko_price_logic(input_data.token_id)


# --- Main Server Execution ---
if __name__ == "__main__":
    # Create the MCP Server instance
    server = MCPServer(
        name="coingecko-price-server-py-sse",
        version="1.1.0",
        title="CoinGecko Price Server (Python/SSE - Simplified)",
        description="Provides CoinGecko cryptocurrency prices via MCP SSE transport using serve_sse."
    )

    # Add the tool instance to the server
    server.add_tool(CoinGeckoPriceTool())
    logger.info(f"Tool '{CoinGeckoPriceTool.name}' added to server.")

    # Get port from environment variable or default
    port = int(os.getenv("PORT", 8000)) # Use 8000 as default if PORT not set

    logger.info(f"Starting MCP SSE server on port {port}...")
    # Use the serve_sse method provided by the SDK
    # This presumably handles the two-endpoint logic internally.
    server.serve_sse(port=port, host="0.0.0.0") # Bind to all interfaces