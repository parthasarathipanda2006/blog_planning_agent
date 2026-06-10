# Blog Planning Agent

An AI-powered technical blog generator built with LangGraph, Groq, and Streamlit. Give it a topic, and it researches, plans, and writes a complete structured blog post in Markdown.

---

## How It Works

The agent routes each topic through a multi-stage pipeline:

```
Topic → Router → [Research?] → Orchestrator → Workers (parallel) → Reducer → Blog
```

**Router** classifies the topic into one of three modes:

| Mode | Description | Example Topics |
|------|-------------|----------------|
| `closed_book` | Evergreen content, no research needed | Gradient descent, CNNs, sorting algorithms |
| `hybrid` | Established concept + recent examples | Current LLM fine-tuning tools, RLHF benchmarks |
| `open_book` | Time-sensitive, research-first | Weekly AI news, recent model releases |

**Research Node** (if needed) runs up to 3 Tavily queries, deduplicates results, and packs them into structured `EvidenceItem` objects.

**Orchestrator** generates a full `Plan` (5–9 sections) with per-section goals, bullets, and target word counts.

**Workers** write each section in parallel via `Send()` map, grounded by evidence and mode.

**Reducer** assembles sections, saves the final Markdown file to disk, and returns it to the UI.

---

## Project Structure

```
├── blog_planning_agent.py   # LangGraph graph, nodes, Pydantic schemas
├── app.py                   # Streamlit frontend
├── blogs.db                 # SQLite checkpointer (auto-created)
└── .env                     # API keys (see setup)
```

---

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

`requirements.txt`:

```
streamlit
langchain-groq
langchain-huggingface
langgraph
langchain-core
langchain-community
langchain-tavily
groq
python-dotenv
pydantic
requests
sentence-transformers
langgraph-checkpoint-sqlite
```

**2. Configure environment**

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key
```

**3. Run the app**

```bash
streamlit run app.py
```

---

## Usage

1. Enter a blog topic in the sidebar text area.
2. Click **Generate**.
3. Watch real-time progress across Router → Research → Planning → Writing → Complete stages.
4. View results across four tabs:
   - **Blog** — final rendered Markdown with a download button
   - **Planning** — section-by-section plan with goals and bullets
   - **Logs** — execution info
   - **Research** — expandable evidence cards with sources and snippets
5. Past generations are saved to the sidebar by title and persist across sessions via SQLite checkpointing.

---

## Stack

| Component | Library |
|-----------|---------|
| LLM | `llama-3.3-70b-versatile` via Groq |
| Orchestration | LangGraph (`StateGraph`, `Send`) |
| Web Search | Tavily (`TavilySearch`) |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` |
| Checkpointing | `SqliteSaver` |
| Frontend | Streamlit |
| Schema validation | Pydantic v2 |

---

## Key Design Decisions

**Parallel section writing** — uses LangGraph's `Send()` primitive to dispatch all section tasks simultaneously, significantly reducing total generation time for long blogs.

**Mode-aware grounding** — workers receive the routing mode and evidence pack, so `open_book` sections only cite provided URLs while `closed_book` sections stay evergreen without hallucinated references.

**Persistent history** — each run gets a UUID `thread_id`. `SqliteSaver` persists full state, so the sidebar can reload any past blog without re-running the graph.

**Optional research field** — Pydantic schema uses `Optional[str]` on nullable fields to prevent Groq from rejecting structured outputs with null values.

---

## Notes

- The blog Markdown file is also written to disk locally as `<blog_title>.md` after each run.
- Research is capped at 2 results per query and 3 queries max to stay within rate limits.
- Tavily's `published_date` field is often missing; the LLM normalizes dates to ISO format when inferable and sets `null` otherwise.
