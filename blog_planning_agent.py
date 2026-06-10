from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langgraph.graph import StateGraph,START,END
from typing import TypedDict,Annotated,Literal,Optional
from dotenv import load_dotenv
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage,BaseMessage,SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
import os
import requests
from groq import APIStatusError
from pydantic import BaseModel,Field
import operator
from langgraph.types import Send
from langchain_tavily import TavilySearch
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
#=========================================MODEL=================================================================================
load_dotenv()

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0
)
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)
#=========================================pydantic classes=================================================================================

conn=sqlite3.connect(database="blogs.db",check_same_thread=False)
checkpointer=SqliteSaver(conn=conn)


class RouterDecision(BaseModel):
    need_research:bool=Field(description="if the topic need search or not" )
    mode:Literal["open_book","hybrid","closed_book"]
    queries:list[str]=Field(description="if need searh what are the queries" )

class EvidenceItem(BaseModel):
    title:str
    url:str
    published_at:Optional[str]
    snippet:Optional[str]
    source:Optional[str]

class EvidencePack(BaseModel):
    evidence:list[EvidenceItem]

class Task(BaseModel):
    title:str
    id:str
    goal:str=Field(
        ...,
        description="one sentence describing what reader should be able tounderstand after the section\n"
    )
    bullets:list[str]=Field(
        ...,
        min_length=3,
        max_length=5,
        description="3-5 concre points,nonoverlapping subpoints to cover in this section"
    )
    target_words:int=Field(
        ...,
        description="target word count for this section (120-450)"
    )
class Plan(BaseModel):
    blog_title:str
    tasks:list[Task]
#=============================================STATE===================================================================
class state(TypedDict):
    routerDecision:RouterDecision
    evidence_pack:list[EvidenceItem]
    Topic:str
    plan:Plan
    sections:Annotated[list[str],operator.add]
    final:str
#=============================================NODES=====================================================================
def router(state:state):

    topic=state["Topic"]
    ROUTER_PROMPT="""You are a routing module for a technical blog planner.

                    Decide whether web research is needed BEFORE planning.

                    Modes:
                    - closed_book (needs_research=false):
                    Evergreen topics where correctness does not depend on recent facts. These are established concepts, theories, or methods that are standard in the field and unlikely to change significantly in the short term.
                    Examples: mathematical concepts (calculus, linear algebra), core algorithms (sorting, searching), established architectures (CNN, RNN, Transformer fundamentals), fundamental principles (gradient descent, backpropagation, bias-variance tradeoff).

                    - hybrid (needs_research=true):
                    Mostly evergreen concepts that benefit from current examples, tools, or recent developments to be practically useful and up-to-date.
                    Examples: applying a standard algorithm to a new domain, recent improvements to established techniques, current best practices, state-of-the-art implementations of classic methods.

                    - open_book (needs_research=true):
                    Topics that are inherently time-sensitive or require very recent information to be accurate and useful.
                    Examples: weekly/daily news, recent releases (models, tools, papers from last few weeks), rankings, pricing information, policy/regulation changes, breaking news, trending topics.

                    Decision Guidelines:
                    - If the topic is about a well-established concept/method that has been stable for years → closed_book
                    - If the topic is about an established concept but asks for recent applications/tools/performance → hybrid
                    - If the topic explicitly asks for "latest", "recent", "this week", "current state" → open_book
                    - If unsure whether current information materially affects correctness → lean toward hybrid

                    If needs_research=true:
                    - Output 3–10 high-signal queries.
                    - Queries should be scoped and specific (avoid generic queries like just "AI" or "LLM").
                    - If user asked for "last week/this week/latest", reflect that constraint IN THE QUERIES.
                    """
    response=llm.with_structured_output(RouterDecision).invoke(
        [
            SystemMessage(
                content=(ROUTER_PROMPT)
            ),
            HumanMessage(
                content=(f"Topic:{topic}")
            )

        ]
    )
    return {"routerDecision":response}
#================================================TAVILY_SEARCH===========================================================
def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Uses TavilySearchResults if installed and TAVILY_API_KEY is set.
    Returns list of dict with common fields. Note: published date is often missing.
    """
    tool = TavilySearch(max_results=max_results)
    results = tool.invoke({"query": query})["results"]
    results=results[:2]
    normalized: list[dict] = []
    for r in results or []:
        normalized.append(
            {
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "snippet": r.get("content") or r.get("snippet") or "",
                "published_at": r.get("published_date") or r.get("published_at"),
                "source": r.get("source"),
            }
        )
    return normalized
#=============================================NODES=====================================================================
def research_node(state:state):
    
    print("USED")
    topic=state["Topic"]
    routerDecision=state["routerDecision"]
    queries=routerDecision.queries[:3]
    raw_result:list[dict]=[]
    seen_url=set()
    for query in queries:
        result=_tavily_search(query,max_results=5)
        for r in result:
            if r.get('url') in seen_url:
                continue
            if not r.get('url'):
                continue
            seen_url.add(r.get('url'))
            raw_result.append(r)
    if not raw_result:
        return {"evidence_pack":[]}
    

    RESEARCH_SYSTEM = """
                        You are a research synthesizer for technical writing.

                        Given raw web search results, produce a deduplicated list of EvidenceItem objects.

                        Rules:
                        - Only include items with a non-empty url.
                        - Prefer relevant + authoritative sources (company blogs, docs, reputable outlets).
                        - Extract/normalize published_at as ISO (YYYY-MM-DD) if you can infer it from title/snippet.
                        If you can't infer a date reliably, set published_at=null (do NOT guess).
                        - Keep snippets short.
                        - Deduplicate by URL.

                    """
    response=llm.with_structured_output(EvidencePack).invoke(
        [
            SystemMessage(
                content=(RESEARCH_SYSTEM)
            ),
            HumanMessage(
                content=(f"raw_result:{raw_result}")
            )
        ]
    )
    return {"evidence_pack":response.evidence}

    

def Orchastrator(state:state):
    
    topic=state["Topic"]
    response=llm.with_structured_output(Plan).invoke(
        [
            SystemMessage(
                content=(
                    """
                        You are a senior technical writer and developer advocate.
                        Your job is to produce a highly actionable outline for a technical blog post.

                        Hard requirements:
                        - Create 5–9 sections (tasks) suitable for the topic and audience.
                        - Each task must include:
                        1) goal (1 sentence)
                        2) 3–6 bullets that are concrete, specific, and non-overlapping
                        3) target word count (120–550)

                        Flexibility:
                        - Do NOT use a fixed taxonomy unless it naturally fits.
                        - You may tag tasks (tags field), but tags are flexible.

                        Quality bar:
                        - Assume the reader is a developer; use correct terminology.
                        - Bullets must be actionable: build/compare/measure/verify/debug.
                        - Ensure the overall plan includes at least 2 of these somewhere:
                        * minimal code sketch / MWE (set requires_code=True for that section)
                        * edge cases / failure modes
                        * performance/cost considerations
                        * security/privacy considerations (if relevant)
                        * debugging/observability tips

                        Grounding rules:
                        - Mode closed_book: keep it evergreen; do not depend on evidence.
                        - Mode hybrid:
                        - Use evidence for up-to-date examples (models/tools/releases) in bullets.
                        - Mark sections using fresh info as requires_research=True and requires_citations=True.
                        - Mode open_book (weekly news roundup):
                        - Set blog_kind = "news_roundup".
                        - Every section is about summarizing events + implications.
                        - DO NOT include tutorial/how-to sections (no scraping/RSS/how to fetch news) unless user explicitly asked for that.
                        - If evidence is empty or insufficient, create a plan that transparently says "insufficient fresh sources"
                            and includes only what can be supported.

                        Output must strictly match the Plan schema.
                        """
                )
            ),
        HumanMessage(
                content=(
                    f"Topic: {topic}"
                    f"mode: {state['routerDecision'].mode}"
                    f"Evidence: {state['evidence_pack']}"
                    f"Instruction: If mode=open_book, your plan must NOT drift into a tutorial."
                )
        )
        ]
    )
    return {"plan":response}


def worker(payload:dict):

    task=payload["task"]
    topic=payload["blog_topic"]
    plan=payload["plan"]
    mode=payload["mode"]

    response=llm.invoke(
        [
            SystemMessage(
                content=(
                    """
                        You are a senior technical writer and developer advocate.
                        Write ONE section of a technical blog post in Markdown.

                        Hard constraints:
                        - Follow the provided Goal and cover ALL Bullets in order (do not skip or merge bullets).
                        - Stay close to Target words (±15%).
                        - Output ONLY the section content in Markdown (no blog title H1, no extra commentary).
                        - Start with a '## <Section Title>' heading.

                        Scope guard (prevents mid-blog topic drift):
                        - If blog_kind == "news_roundup": do NOT turn this into a tutorial/how-to guide.
                        Do NOT teach web scraping, RSS, automation, or "how to fetch news" unless bullets explicitly ask for it.
                        Focus on summarizing events and implications.

                        Grounding policy:
                        - If mode == open_book (weekly news):
                        - Do NOT introduce any specific event/company/model/funding/policy claim unless it is supported by provided Evidence URLs.
                        - For each event claim, attach a source as a Markdown link: ([Source](URL)).
                        - Only use URLs provided in Evidence. If not supported, write: "Not found in provided sources."
                        - If requires_citations == true (hybrid sections):
                        - For outside-world claims, cite Evidence URLs the same way.
                        - Evergreen reasoning (concepts, intuition) is OK without citations unless requires_citations is true.

                        Code:
                        - If requires_code == true, include at least one minimal, correct code snippet relevant to the bullets.

                        Style:
                        - Short paragraphs, bullets where helpful, code fences for code.
                        - Avoid fluff/marketing. Be precise and implementation-oriented.
                        """

                ) 
            ),
            HumanMessage(
                content=(
                    f"blog_title:{plan.blog_title}\n"
                    f"Topic:{topic}\n"
                    f"task:{task.title}\n"
                    f"goal:{task.goal}\n"
                    f"bullets:{task.bullets}\n"
                    f"target_words:{task.target_words}\n"
                    f"Mode: {mode}"
                    f"evidencec:{payload['evidence']}"
                    "return only the Mark down content"
                )
            )
        ]    
    ).content.strip()

    return {"sections":[response]}

def planner(state:state):

    tasks=state["plan"].tasks

    return [
        Send(
            "worker",
            {
                "task":task,
                "blog_topic":state['Topic'],
                "plan":state['plan'],
                "mode":state['routerDecision'].mode,
                "evidence":state['evidence_pack']
            }
        )
        for task in tasks
    ]
def reducer(state:state):

    title=state["plan"].blog_title
    body="\n\n".join(state["sections"]).strip()

    final_md=f"# {title}\n\n{body}\n"
    filename = f"{title}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(final_md)
    return {"final":final_md}

#====================================================GRAPH=================================================================
def condition(state:state):
    if state["routerDecision"].need_research==True:
        return "research"
    else: 
        return "orch"

graph=StateGraph(state)
graph.add_node("router",router)
graph.add_node("research",research_node)
graph.add_node("orch",Orchastrator)
graph.add_node("worker",worker)
graph.add_node("reducer",reducer)

graph.add_edge(START,"router")
graph.add_conditional_edges(
    "router",
    condition,
    {
        "research":"research",
        "orch":"orch"
    }
)
graph.add_edge("research","orch")
graph.add_conditional_edges("orch",planner,["worker"])
graph.add_edge("worker","reducer")
graph.add_edge("reducer",END)

chatbot=graph.compile(checkpointer=checkpointer)

def extract_pointer():
    emp_set=set()
    for pointer in checkpointer.list(None):
        emp_set.add(pointer.config["configurable"]["thread_id"])
    list_pointers=list(emp_set)
    return list_pointers

# Test different topic types
#print("Testing self Attention (should be closed_book):")
#result1 = chatbot.invoke({"Topic": "LSTM", "evidence_pack": []})
#print(f"Needs research: {result1['routerDecision'].need_research}")
#print(f"Mode: {result1['routerDecision'].mode}")
#print()

