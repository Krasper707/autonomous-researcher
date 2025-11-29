import os
import json
import logging
from typing import TypedDict, List, Dict, Any
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from tavily import TavilyClient

# --- CONFIGURATION ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- STATE DEFINITION ---
class AgentState(TypedDict):
    task: str
    plan: List[str]             # Changed to List for multiple search steps
    draft: str
    critique: str
    content: List[str]
    revision_number: int
    max_revisions: int
    error_log: List[str]        # New: Track errors for debugging

# --- SETUP TOOLS & LLM ---
llm = ChatOpenAI(
    model="openai/gpt-oss-20b:free",
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
    temperature=0.2,            # Lower temp for more deterministic logic
    model_kwargs={"response_format": {"type": "json_object"}} # Force JSON where possible
)

tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

# --- ROBUST UTILITIES ---

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def safe_search(query: str) -> str:
    """Retries search 3 times if it fails."""
    try:
        results = tavily.search(query=query, max_results=3)
        if not results.get('results'):
            return f"No results found for query: {query}"
        
        # Deduplicate and format
        context = ""
        seen_urls = set()
        for res in results['results']:
            if res['url'] not in seen_urls:
                context += f"Source: {res['url']}\nSnippet: {res['content']}\n\n"
                seen_urls.add(res['url'])
        return context
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise e  # Tenacity will catch this and retry

# --- PROMPT ENGINEERING ---

PLANNER_PROMPT = """
You are a Lead Research Strategist.
Given a user request, create a targeted research plan consisting of 3 distinct search queries.
Do not use generic queries. Focus on specific aspects (e.g., "Market size", "Technical limitations", "Key Competitors").

OUTPUT FORMAT:
Return valid JSON only:
{
    "queries": ["query 1", "query 2", "query 3"]
}
"""

WRITER_PROMPT = """
You are a Senior Technical Writer. Your goal is to write a comprehensive Markdown report.

INPUT DATA:
{content}

PREVIOUS CRITIQUE (Fix these issues):
{critique}

INSTRUCTIONS:
1. Use professional Markdown formatting (## Headers, **Bold**, tables).
2. Synthesize the research. Do not just list facts; tell a story.
3. If the research is missing information, state "Data not found" for that section.
4. Cite sources using [URL] format.
"""

CRITIC_PROMPT = """
You are a Chief Editor. Grade the report strictly.

CRITERIA:
1. Did it answer the user's task?
2. Are the claims backed by the research provided?
3. Is the formatting clean?

OUTPUT FORMAT:
Return valid JSON only:
{
    "score": (integer 0-100),
    "status": "APPROVE" or "REJECT",
    "feedback": "Specific instructions on what to fix."
}
"""

# --- AGENT NODES ---

def planner_node(state: AgentState):
    print("---PLANNER: Strategizing---")
    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=state['task'])
    ]
    try:
        response = llm.invoke(messages)
        plan_json = json.loads(response.content)
        return {"plan": plan_json.get("queries", [state['task']])}
    except Exception as e:
        logger.error(f"Planner JSON error: {e}")
        return {"plan": [state['task']], "error_log": [str(e)]}

def researcher_node(state: AgentState):
    print("---RESEARCHER: Executing Plan---")
    content_results = []
    
    for query in state['plan']:
        print(f"  --> Searching: {query}")
        result = safe_search(query)
        content_results.append(result)
        
    return {"content": content_results}

def writer_node(state: AgentState):
    print("---WRITER: Drafting---")
    full_content = "\n\n".join(state['content'])
    
    writer_llm = ChatOpenAI(
        model="openai/gpt-oss-20b:free",
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        temperature=0.4 
    )
    
    messages = [
        SystemMessage(content=WRITER_PROMPT.format(
            content=full_content, 
            critique=state.get('critique', 'None')
        )),
        HumanMessage(content="Write the report.")
    ]
    response = writer_llm.invoke(messages)
    return {
        "draft": response.content,
        "revision_number": state.get("revision_number", 1) + 1
    }

def critic_node(state: AgentState):
    print("---CRITIC: Reviewing---")
    messages = [
        SystemMessage(content=CRITIC_PROMPT),
        HumanMessage(content=f"Task: {state['task']}\n\nDraft:\n{state['draft']}")
    ]
    try:
        response = llm.invoke(messages)
        critique_json = json.loads(response.content)
        
        feedback_msg = f"Score: {critique_json['score']}/100. Feedback: {critique_json['feedback']}"
        status = critique_json['status']
        
        return {"critique": f"{status}: {feedback_msg}"}
        
    except Exception as e:
        logger.error(f"Critic parsing error: {e}")
        return {"critique": "REJECT: System Error in Critique formatting. Please refine style."}


def should_continue(state: AgentState):
    critique = state['critique']
    revision_number = state['revision_number']
    max_revisions = state['max_revisions']

    if "APPROVE" in critique:
        print("---DECISION: APPROVE---")
        return END
    
    if revision_number > max_revisions:
        print("---DECISION: MAX REVISIONS REACHED---")
        return END
    
    print(f"---DECISION: REJECT (Score too low)---")
    return "writer"


workflow = StateGraph(AgentState)
workflow.add_node("planner", planner_node)
workflow.add_node("researcher", researcher_node)
workflow.add_node("writer", writer_node)
workflow.add_node("critic", critic_node)

workflow.set_entry_point("planner")

workflow.add_edge("planner", "researcher")
workflow.add_edge("researcher", "writer")
workflow.add_edge("writer", "critic")
workflow.add_conditional_edges("critic", should_continue, {END: END, "writer": "writer"})

app = workflow.compile()

if __name__ == "__main__":
    task = "Analyze the impact of AI on Junior Developer jobs in 2025."
    initial_state = {
        "task": task,
        "max_revisions": 2,
        "revision_number": 0,
        "content": [],
        "plan": [],
        "draft": "",
        "critique": "",
        "error_log": []
    }
    
    result = app.invoke(initial_state)
    print("\nFINAL REPORT:\n", result['draft'])