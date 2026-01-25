"""Simple MCP server with trivial tools."""

import logging
import os
import sys
from datetime import datetime

import uvicorn
from fastmcp import FastMCP
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Create FastMCP instance
mcp = FastMCP("openwebui-tools")


# Tool input models
class GreetingInput(BaseModel):
    name: str = Field(description="Name of the person to greet")
    language: str = Field(default="en", description="Language code (en, es, fr)")


class MathInput(BaseModel):
    operation: str = Field(description="Math operation: add, subtract, multiply, divide")
    a: float = Field(description="First number")
    b: float = Field(description="Second number")


class InfoInput(BaseModel):
    query: str = Field(description="Information query type: time, date, server")


# Register tools
@mcp.tool()
async def greet(data: GreetingInput) -> str:
    """Greet someone in different languages."""
    greetings = {
        "en": f"Hello, {data.name}!",
        "es": f"¡Hola, {data.name}!",
        "fr": f"Bonjour, {data.name}!",
        "de": f"Guten Tag, {data.name}!",
    }
    return greetings.get(data.language, greetings["en"])


@mcp.tool()
async def calculate(data: MathInput) -> str:
    """Perform basic mathematical operations."""
    operations = {
        "add": lambda a, b: a + b,
        "subtract": lambda a, b: a - b,
        "multiply": lambda a, b: a * b,
        "divide": lambda a, b: a / b if b != 0 else "Error: Division by zero",
    }

    if data.operation not in operations:
        return f"Error: Unknown operation '{data.operation}'"

    result = operations[data.operation](data.a, data.b)
    return f"{data.a} {data.operation} {data.b} = {result}"


@mcp.tool()
async def get_info(data: InfoInput) -> str:
    """Get server information like current time, date, or server status."""
    now = datetime.now()

    info_types = {
        "time": f"Current time: {now.strftime('%H:%M:%S')}",
        "date": f"Current date: {now.strftime('%Y-%m-%d')}",
        "server": "MCP Server Status: Running on OpenWebUI",
        "datetime": f"Current datetime: {now.strftime('%Y-%m-%d %H:%M:%S')}",
    }

    return info_types.get(data.query.lower(), f"Available queries: {', '.join(info_types.keys())}")


if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SERVER_PORT", "8090"))

    logger.info("Starting MCP server on %s:%s", host, port)
    logger.info("Registered tools: greet, calculate, get_info")

    app = mcp.http_app(path="/mcp")
    logger.info("MCP endpoint available at http://%s:%s/mcp", host, port)

    uvicorn.run(app, host=host, port=port, log_level="info")
