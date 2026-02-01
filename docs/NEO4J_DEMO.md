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

Graph
1. neo4j_execute_cypher — Query the graph. Use when the user asks about papers, authors, topics, or custom analysis. Pass "query" (Cypher) and optionally "params". Read-only only (MATCH, RETURN, etc.); writes are blocked.
2. link_papers — Manually add a citation edge: citing_arxiv_id (paper that cites) and cited_arxiv_id (paper cited). Both papers must already exist; add them first with arxiv_add_paper or semantic_scholar_paper.

arXiv (metadata only)
3. arxiv_search — Search arXiv by topic. Returns paper IDs and titles. Use when the user wants to find papers by keyword.
4. arxiv_add_paper — Add an arXiv paper to the graph by arXiv ID (e.g. 2301.07041 or URL). Fetches title, authors, topics from arXiv only. Safe to call multiple times.

Semantic Scholar (papers, authors, citations, embeddings)
5. semantic_scholar_paper — Get a paper by S2 ID, ARXIV:..., DOI:..., or URL. Returns details; optionally add to Neo4j; optionally include_embedding for later similarity search.
6. semantic_scholar_search — Search papers by keyword (broader than arXiv). Returns paper IDs; add with semantic_scholar_paper. Supports year, fields_of_study, min_citations, open_access_only.
7. semantic_scholar_author — Get author by Semantic Scholar author ID. Optionally add to graph and include their papers.
8. semantic_scholar_author_search — Search authors by name. Returns author IDs for semantic_scholar_author.
9. semantic_scholar_expand_citations — Expand a paper's references (papers it cites) or citations (papers citing it). Use direction='references' or 'citations'. Optionally add fetched papers and CITES edges to the graph.
10. semantic_scholar_similar_papers — Find papers similar to a given paper (by embedding). Paper must have an embedding in the graph; use semantic_scholar_add_embeddings first.
11. semantic_scholar_add_embeddings — Batch-add SPECTER2 embeddings to papers in the graph (rate-limited). Enables semantic_scholar_similar_papers.
12. semantic_scholar_cluster_papers — Cluster papers by embedding similarity. Requires embeddings (run semantic_scholar_add_embeddings first). Optional topic filter.

Influence (require papers in graph)
13. compute_paper_influence — Influence metrics for one paper: citations, PageRank, betweenness, citation velocity, trends. Paper identified by paper_id (arXiv ID, Semantic Scholar ID, or DOI).
14. find_most_influential_papers — Top papers by topic and/or min_year, ranked by metric (pagerank, citations, betweenness). Returns paper_id (arXiv or S2), title, year, scores.

Graph schema:
- Nodes: Paper (arxiv_id, s2_id, title, year, abstract, citations, embedding, ...), Author (name, s2_id, ...), Topic (name)
- Relationships: CITES (Paper -> Paper), AUTHORED (Author -> Paper), ABOUT (Paper -> Topic)

When to use which:
- Finding papers by topic: arxiv_search or semantic_scholar_search (SS is broader).
- Adding a paper by arXiv ID (metadata only): arxiv_add_paper.
- Adding a paper with rich metadata / citations: semantic_scholar_paper (then semantic_scholar_expand_citations for refs/citations).
- Adding citation edges: semantic_scholar_expand_citations, or link_papers if both papers already in graph.
- Similar papers: semantic_scholar_add_embeddings then semantic_scholar_similar_papers.
- Influence: compute_paper_influence (paper_id), find_most_influential_papers.
```

## Tools

The MCP server exposes graph, arXiv, Semantic Scholar, and influence tools. The system prompt above lists them and when to use each.

| Tool | Description |
|------|-------------|
| **Graph** | |
| `neo4j_execute_cypher` | Execute read-only Cypher queries against the citation graph |
| `link_papers` | Link two papers already in the graph (citing → cited) |
| **arXiv** | |
| `arxiv_search` | Search arXiv by topic; returns paper IDs and titles |
| `arxiv_add_paper` | Add an arXiv paper to the graph (metadata from arXiv only) |
| **Semantic Scholar** | |
| `semantic_scholar_paper` | Get paper by S2/ARXIV/DOI/URL; optionally add to graph and include embedding |
| `semantic_scholar_search` | Search papers (broader than arXiv); filter by year, field, citations |
| `semantic_scholar_author` | Get author by S2 ID; optionally add to graph and fetch papers |
| `semantic_scholar_author_search` | Search authors by name |
| `semantic_scholar_expand_citations` | Fetch references or citations for a paper; optionally add to graph |
| `semantic_scholar_similar_papers` | Find similar papers by embedding (run add_embeddings first) |
| `semantic_scholar_add_embeddings` | Batch-add SPECTER2 embeddings to papers in graph |
| `semantic_scholar_cluster_papers` | Cluster papers by embedding (requires embeddings) |
| **Influence** | |
| `compute_paper_influence` | Influence metrics for one paper; paper_id = arXiv ID, S2 ID, or DOI |
| `find_most_influential_papers` | Top papers by topic/year and metric |

**neo4j_execute_cypher safety:** Queries are validated; only read-only operations (MATCH, RETURN, etc.) are allowed. Dangerous operations (DELETE, DROP, CREATE, MERGE, SET) are blocked.

## Neo4j Browser (local only)

Inspect the graph at `http://localhost:7474`. Sign in with user `neo4j` and `NEO4J_PASSWORD` (default `password123`).

**Environment:** Neo4j connection uses `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`. See [env.example](../env.example); defaults are fine for local dev.
