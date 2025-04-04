from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_sse_app(mcp: FastMCP) -> Starlette:
    """
    Creates a Starlette application to handle MCP SSE transport.

    Args:
        mcp: The FastMCP instance containing the core MCP server logic.

    Returns:
        A Starlette application configured for SSE transport.
    """
    # Initialize the SSE transport, specifying the path for POST messages
    # The transport will handle sending responses/notifications via the SSE stream
    # and receiving requests via POST requests to the specified path.
    transport = SseServerTransport("/messages/")
    logger.info("SseServerTransport initialized for /messages/")

    async def handle_sse_connection(request):
        """
        Handles incoming GET requests to establish the SSE stream.
        Connects the MCP server logic to the transport for this connection.
        """
        logger.info(f"Incoming SSE connection request: {request.url}")
        # The connect_sse context manager handles setting up SSE headers
        # and managing the connection lifecycle.
        async with transport.connect_sse(request) as streams:
            logger.info("SSE stream connected. Running MCP server logic.")
            # The mcp._mcp_server holds the core Server instance from the SDK.
            # run() processes incoming requests from the transport's input stream
            # and sends responses via the transport's output stream.
            await mcp._mcp_server.run(streams, streams)
            logger.info("MCP server run loop finished for this SSE connection.")

    # Define the routes for the Starlette app
    # GET /sse/ : Establishes the SSE connection
    # POST /messages/ : Receives client requests (handled by transport.handle_post_message)
    routes = [
        Route("/sse/", handle_sse_connection),
        Mount("/messages/", transport.handle_post_message) # Mount the transport's POST handler
    ]

    return Starlette(routes=routes)