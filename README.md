# OpenWebUI Document Assistant

An OpenWebUI starter.

## Features

- **Web UI**: OpenWebUI interface for interactive document querying
- **Document Upload**: Upload PDFs and documents directly in the UI
- **RAG**: Built-in vector search and retrieval
- **LLM Integration**: Connect to any LLM via OpenRouter
- **MCP Server**: Model Context Protocol server with extensible tools

## Quick Start

1. **Clone and configure**
   ```bash
   cp env.example .env
   # Edit .env with your settings
   ```

2. **Start services**
   ```bash
   make dev
   ```

3. **Access OpenWebUI**

   Open http://localhost:3000 in your browser

4. **Configure LLM (OpenRouter)**

   - Go to **Admin Settings** → **Connections**
   - Click **Manage OpenAI Connections** → **Add Connection**
   - Set:
     - **URL**: `https://openrouter.ai/api/v1`
     - **API Key**: Your OpenRouter API key (get one at [openrouter.ai](https://openrouter.ai))
   - Save

5. **Upload Documents**

   - Go to **Workspace** → **Knowledge**
   - Create a new knowledge base
   - Upload your PDF documents
   - Documents are automatically embedded and indexed

6. **Create a Model**

   - Go to **Workspace** → **Models**
   - Create a new model
   - Attach your knowledge base to the model
   - Save

7. **Start Querying**

   - Start a new chat
   - Select the model you created above
   - Ask questions about your documents

## Available Commands

```bash
make dev          # Start local development (http://localhost:3000)
make dev-down     # Stop local development

make prod         # Start production (with Caddy reverse proxy)
make prod-down    # Stop production

make deploy                # Deploy main branch to EC2
make deploy BRANCH=feature # Deploy specific branch

make clean        # Clean up Docker images and containers
```

## Project Structure

```
openweb/
├── docker-compose.yaml         # Base configuration
├── docker-compose.override.yaml # Local dev overrides
├── docker-compose.prod.yaml    # Production with Caddy
├── mcp-server/                 # MCP server for extensible tools
│   ├── server.py              # FastMCP server implementation
│   ├── Dockerfile             # MCP server container
│   └── README.md              # MCP server documentation
├── webserver/                  # Caddy reverse proxy
│   ├── Caddyfile              # Production config
│   └── Caddy.Dockerfile
├── scripts/                    # Deployment scripts
│   ├── deploy.sh              # Git-based deploy to EC2
│   └── setup-ec2-docker.sh
└── docs/
    └── DEPLOYMENT.md          # Production deployment guide
```

## Production Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full production deployment instructions.

Quick overview:
1. Set up your EC2 instance
2. Update `.env` with your EC2 public IP address
3. Run `make prod`

Access via `http://YOUR_EC2_IP_ADDRESS`

## MCP Server

An integrated Model Context Protocol (MCP) server runs alongside OpenWebUI, providing extensible tools for enhanced functionality.

**Available Tools:**
- **greet**: Multi-language greetings
- **calculate**: Basic math operations  
- **get_info**: Server information (time, date, status)

**Access:**
- MCP endpoint: `http://localhost:8090/mcp` (local dev)
- From containers: `http://mcp-server:8090/mcp`

See [mcp-server/README.md](mcp-server/README.md) for more details on extending the MCP server with custom tools.
