# MCP Server for OpenWebUI

A simple Model Context Protocol (MCP) server that provides trivial tools for demonstration purposes.

## Features

This MCP server provides three simple tools:

1. **greet**: Greet someone in different languages (English, Spanish, French, German)
2. **calculate**: Perform basic math operations (add, subtract, multiply, divide)
3. **get_info**: Get server information (current time, date, server status)

## Architecture

The MCP server runs as a separate Docker service alongside OpenWebUI:

```
┌─────────────┐         ┌─────────────┐
│  OpenWebUI  │◄───────►│ MCP Server  │
│   :3000     │  HTTP   │   :8090     │
└─────────────┘         └─────────────┘
```

## Running the Server

The MCP server is integrated into the docker-compose setup:

```bash
# Start all services (OpenWebUI + MCP Server)
make prod

# Or with docker-compose directly
docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
```

The MCP server will be available at:
- From OpenWebUI container: `http://mcp-server:8090/mcp`
- From host machine: `http://localhost:8090/mcp`

## Testing the Server

You can test the MCP server endpoint:

```bash
# Check if server is running
curl http://localhost:8090/mcp

# From inside a container
curl http://mcp-server:8090/mcp
```

## Tools Documentation

### greet
Greet someone in different languages.

**Input:**
- `name` (string): Name of the person to greet
- `language` (string, optional): Language code (en, es, fr, de). Default: "en"

**Example:**
```json
{
  "name": "Alice",
  "language": "es"
}
```

**Output:** "¡Hola, Alice!"

### calculate
Perform basic mathematical operations.

**Input:**
- `operation` (string): Math operation (add, subtract, multiply, divide)
- `a` (float): First number
- `b` (float): Second number

**Example:**
```json
{
  "operation": "multiply",
  "a": 7,
  "b": 6
}
```

**Output:** "7 multiply 6 = 42"

### get_info
Get server information.

**Input:**
- `query` (string): Information query type (time, date, server, datetime)

**Example:**
```json
{
  "query": "time"
}
```

**Output:** "Current time: 14:30:45"

## Configuration

The MCP server uses the following environment variables:

- `MCP_SERVER_HOST`: Host to bind to (default: "0.0.0.0")
- `MCP_SERVER_PORT`: Port to bind to (default: "8090")

These are configured in `docker-compose.prod.yaml`.

## Development

The project uses [uv](https://docs.astral.sh/uv/) for Python package management:

```bash
# Install dependencies
uv sync

# Run locally
uv run python server.py

# Add a new dependency
uv add package-name
```

Dependencies are defined in `pyproject.toml`.

## Extending the Server

To add new tools:

1. Define a Pydantic input model for your tool's parameters
2. Create an async function decorated with `@mcp.tool()`
3. The tool will be automatically registered and available to clients

Example:

```python
class MyToolInput(BaseModel):
    param: str = Field(description="Parameter description")

@mcp.tool()
async def my_tool(input: MyToolInput) -> str:
    """Tool description that clients will see."""
    return f"Result for: {input.param}"
```
