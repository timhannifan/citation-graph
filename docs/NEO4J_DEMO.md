# Citation graph (Neo4j + MCP)

The MCP server talks to Neo4j and exposes citation-graph tools so OpenWebUI chat can query and extend the graph. A seed/demo script populates the DB and runs example queries; the server exposes tools including `neo4j_execute_cypher`, arXiv search, add paper, and influence metrics.

## Why knowledge graphs?

- **Model relationships naturally** — Entities and links map directly to nodes and edges; no heavy normalization or junction tables.
- **Traverse efficiently** — Follow connections in one hop; path and neighborhood queries stay simple.
- **Discover patterns** — Structure and connectivity (clusters, centrality, paths) are first-class.
- **Query relationships directly** — No JOINs; add relationship types without schema churn.

The stack uses a **citation graph**: nodes = Papers, Authors, Topics; edges = CITES, AUTHORED, ABOUT. Node properties include title/year/citation_count on papers, name/affiliation on authors.

## Prerequisites

- Docker Compose (`make dev` or `make prod`).

## Quick start

1. **Start the stack**  
   `make dev` or `make prod`.

2. **Seed the citation graph (once)**  
   ```bash
   make seed-db
   ```
   Runs the seed/demo script inside the mcp-server container. Run anytime to reset and re-seed.

3. **Connect the MCP server in OpenWebUI**  
   Admin Settings → External Tools → Add Connection → URL. In a chat, enable tools via Integrations.

4. **Edit the chat system prompt**  
   Use the controls in the upper right of the chat to open the system prompt / custom instructions. Paste the [System prompt](#system-prompt) block below.

5. **Use the citation graph tools in chat**  
   Enable the MCP tools in Integrations and ask about the citation graph (e.g. "Find papers by Alice Chen", "Search for papers on transformers", "Add paper 1609.02907").

## System prompt

Paste into the chat system prompt (upper-right controls):

```
You have access to a Neo4j citation graph with these tools:

1. neo4j_execute_cypher — For querying the graph. When the user asks about the citation graph, papers, authors, or research, use this. Pass the Cypher as the "query" parameter; optionally "params" for parameters. Queries must be read-only (MATCH, RETURN, etc.); write operations are blocked.

2. arxiv_search — Search arXiv for papers. Use when the user wants to find papers by topic. Returns paper IDs and titles; the user can then add papers with arxiv_add_paper.

3. arxiv_add_paper — Add an arXiv paper to the citation graph. Provide the arXiv ID (e.g. 2301.07041 or full URL). Optionally include_references (papers this one cites) and include_citations (papers that cite this one); both use Semantic Scholar. Safe to call multiple times.

4. link_papers — Manually link two papers: citing_arxiv_id (the paper that cites) and cited_arxiv_id (the paper being cited). Both papers must already exist in the graph (add them first with arxiv_add_paper if needed).

Graph schema:
- Nodes: Paper (arxiv_id, title, year, abstract, citations), Author (name), Topic (name)
- Relationships: CITES (Paper -> Paper), AUTHORED (Author -> Paper), ABOUT (Paper -> Topic)

Example flows:
- "Find papers by Alice Chen" → neo4j_execute_cypher(query="MATCH (a:Author {name: 'Alice Chen'})-[:AUTHORED]->(p:Paper) RETURN p.title, p.year")
- "Search for papers on transformers" → arxiv_search(query="transformers")
- "Add paper 2301.07041 to the graph" → arxiv_add_paper(arxiv_id="2301.07041")
- "Link paper A as citing paper B" → link_papers(citing_arxiv_id="...", cited_arxiv_id="...")
```

## Tools

The MCP server exposes arXiv, graph, and influence tools. The system prompt above lists them and when to use each. Key tools:

| Tool | Description |
|------|-------------|
| `arxiv_search` | Search arXiv by topic; returns paper IDs and titles |
| `arxiv_add_paper` | Add an arXiv paper to the graph (optionally with refs/citations via Semantic Scholar) |
| `link_papers` | Link two papers already in the graph (citing → cited) |
| `neo4j_execute_cypher` | Execute read-only Cypher queries against the citation graph |
| `compute_paper_influence` | Influence metrics for one paper (citations, PageRank, trends) |
| `compare_paper_influence` | Compare influence across multiple papers |
| `find_most_influential_papers` | Top papers by topic/year and metric |

**neo4j_execute_cypher safety:** Queries are validated; only read-only operations (MATCH, RETURN, etc.) are allowed. Dangerous operations (DELETE, DROP, CREATE, MERGE, SET) are blocked.

## Neo4j Browser (local only)

Inspect the graph at `http://localhost:7474`. Sign in with user `neo4j` and `NEO4J_PASSWORD` (default `password123`).

**Environment:** Neo4j connection uses `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`. See [env.example](../env.example); defaults are fine for local dev.
