# citations

Citation knowledge-graph stack using Neo4j and MCP.

A ready-to-run stack that pairs OpenWebUI with an MCP server backed by a Neo4j citation graph (papers, authors, topics). Tools support searching arXiv, adding papers to the graph, querying the graph with Cypher, and computing influence metrics. Connect via MCP using Docker Compose.

## Features

- **OpenWebUI**: Chat and document assistance with tools enabled
- **MCP server**: FastMCP server exposing citation-graph tools (arXiv search, add paper, Cypher queries, influence metrics)
- **Neo4j**: Citation graph (Paper, Author, Topic; CITES, AUTHORED, ABOUT)

## Quick Start

1. **Clone and configure**

   From the repo root:
   ```bash
   cp env.example .env
   # Edit .env with your settings
   ```

2. **Start services**
   ```bash
   make dev
   ```

3. **Seed the graph**

   Run `make seed-db` once to seed the Neo4j citation graph (papers, authors, topics).

4. **Access OpenWebUI**

   Open http://localhost:3000 in your browser

5. **Configure LLM (OpenRouter)**

   - Go to **Admin Settings** → **Connections**
   - Click **Manage OpenAI Connections** → **Add Connection**
   - Set:
     - **URL**: `https://openrouter.ai/api/v1`
     - **API Key**: Your OpenRouter API key (get one at [openrouter.ai](https://openrouter.ai))
   - Save

6. **Connect MCP Server**
   
   - Go to **Admin Settings** → **External Tools**
   - Under **Manage Tool Servers**, click **Add Connection**
   - Set:
     - **URL**: `http://host.docker.internal:8090/mcp` (use `host.docker.internal` for local dev)
     - **Auth**: `None` (no authentication required)
   - Save
   - In a chat, click the **Integrations** icon (below the text input area)
   - Find your tools and turn them on
   - Tools are now available in chat

7. **Paste the system prompt**

   So the model uses the right tools, open the chat **system prompt** (menu in the chat → system prompt / custom instructions) and paste the prompt from [docs/NEO4J_DEMO.md](docs/NEO4J_DEMO.md#system-prompt). It describes all tools (arXiv search, add paper, Cypher queries, influence metrics) and when to use each.

8. **Start using the stack**

   In a chat with tools enabled, you can search arXiv, add papers to the graph, query the graph (e.g. “Find papers by Alice Chen”), and compute influence metrics.

## Available Commands

```bash
make dev          # Start local development (http://localhost:3000)
make dev-down     # Stop local development
make seed-db      # Seed Neo4j citation graph (run after make dev; required for tools)
make clean        # Clean up Docker images and containers
```

## Project structure

```
citations/
├── LICENSE
├── docker-compose.yaml         # Base configuration
├── docker-compose.override.yaml # Local dev overrides
├── mcp-server/                 # MCP server (Neo4j + arXiv tools)
│   ├── server.py              # FastMCP server; registers tools
│   ├── neo4j_driver.py        # Neo4j driver and query utils
│   ├── tools/                 # MCP tool modules
│   │   ├── arxiv.py           # arxiv_search, arxiv_add_paper (arXiv metadata)
│   │   ├── semantic_scholar.py # SS API client: citation/reference lookup, rate limit
│   │   ├── graph.py           # link_papers, neo4j_execute_cypher
│   │   └── influence.py       # compute/compare influence, find_most_influential
│   ├── Dockerfile
│   └── README.md
├── scripts/
│   └── neo4j_citation_demo.py # Seed and demo for Neo4j citation graph
└── docs/
    └── NEO4J_DEMO.md          # Citation graph schema, system prompt, usage
```

## Citation graph and MCP tools

The MCP server exposes tools for the Neo4j citation graph: `arxiv_search`, `arxiv_add_paper`, `link_papers`, `neo4j_execute_cypher`, `compute_paper_influence`, `compare_paper_influence`, `find_most_influential_papers`. For schema, Cypher examples, and Neo4j Browser, see [docs/NEO4J_DEMO.md](docs/NEO4J_DEMO.md).

## License

[BSD 3-Clause](LICENSE) — Copyright 2026, Tim Hannifan.
