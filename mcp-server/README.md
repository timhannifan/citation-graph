# MCP Server for OpenWebUI

MCP server with Neo4j citation graph and arXiv tools. Exposes tools for searching arXiv, adding papers to the graph, running Cypher queries, and computing influence metrics (e.g. `arxiv_search`, `arxiv_add_paper`, `neo4j_execute_cypher`, `compute_paper_influence`, `find_most_influential_papers`).

## Features

- **arXiv**: `arxiv_search`, `arxiv_add_paper` (metadata from arXiv only)
- **Graph**: `neo4j_execute_cypher` (read-only Cypher), `link_papers`
- **Influence**: `compute_paper_influence` (paper_id), `find_most_influential_papers`

The graph is seeded by running `make seed-db` from the repo root. See [Citation graph (Neo4j + MCP)](../docs/NEO4J_DEMO.md) for schema, system prompt, and usage.

## Running

The MCP server is part of the docker-compose stack:

```bash
make dev    # Local development
make prod   # Production
```

Endpoint: `http://localhost:8090/mcp` (from host) or `http://mcp-server:8090/mcp` (from containers).
