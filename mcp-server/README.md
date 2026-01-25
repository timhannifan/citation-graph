# MCP Server for OpenWebUI

A simple Model Context Protocol (MCP) server demonstrating FastMCP integration with OpenWebUI.

## Features

Provides three example tools:
- **greet**: Multi-language greetings
- **calculate**: Basic math operations
- **get_info**: Server information (time, date, status)

## Running

The MCP server is integrated into the docker-compose setup:

```bash
make dev    # Local development
make prod   # Production
```

Available at `http://localhost:8090/mcp` (from host) or `http://mcp-server:8090/mcp` (from containers).

## Development

Uses [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
uv sync                    # Install dependencies
uv run python server.py    # Run locally
uv add package-name         # Add dependency
```

## Extending

Add new tools by defining a Pydantic input model and decorating a function with `@mcp.tool()`:

```python
class MyToolInput(BaseModel):
    param: str = Field(description="Parameter description")

@mcp.tool()
async def my_tool(data: MyToolInput) -> str:
    """Tool description."""
    return f"Result: {data.param}"
```

See `server.py` for examples.
