"""MCP server for OpenWebUI with Neo4j citation-graph tools."""

import logging
import os
import sys

import uvicorn
from fastmcp import FastMCP
from tools.arxiv import register as register_arxiv
from tools.graph import register as register_graph
from tools.influence import register as register_influence
from tools.semantic_scholar import register as register_semantic_scholar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
    force=True,
)
logger = logging.getLogger(__name__)
sys.stderr.flush()

mcp = FastMCP("openwebui-tools")
register_arxiv(mcp)
register_graph(mcp)
register_influence(mcp)
register_semantic_scholar(mcp)

if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SERVER_PORT", "8090"))

    logger.info("Starting MCP server on %s:%s", host, port)

    app = mcp.http_app(path="/mcp")
    logger.info("MCP endpoint available at http://%s:%s/mcp", host, port)

    uvicorn.run(app, host=host, port=port, log_level="info")
