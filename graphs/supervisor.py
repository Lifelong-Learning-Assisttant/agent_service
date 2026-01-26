import logging
import os
from typing import Dict, List, Any, Optional, Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from state import AgentState
from graphs.chat import chat_graph
from graphs.quiz import quiz_graph
from graphs.retrieval import retrieval_graph
from llm_service.llm_client import LLMClient
from settings import get_settings

log = logging.getLogger(__name__)

# --- Models for Structured Output ---

class SupervisorOutput(BaseModel):
    """Output of the supervisor node."""
    intent: Literal["chat", "quiz", "algo", "search"] = Field(
        description="The primary intent of the user message."
    )
    reasoning: str = Field(description="Brief explanation of the intent choice")

# --- Nodes ---

async def supervisor_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    The main brain of the system. Determines the global intent and routes to subgraphs.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(
            step="supervisor",
            message="Анализ глобального намерения...",
            tool="supervisor"
        )

    question = (state.get("question") or "").strip()
    
    # 1. Deterministic CLI commands (High Priority)
    if question == "/finish_quizz" or question == "/skip_question" or question.startswith("/answer"):
        return {"intent": "quiz"}
    
    # 2. Context-based routing
    quiz_active = state.get("quiz_questions") and len(state.get("quiz_questions")) > 0
    if quiz_active and state.get("interaction_mode") == "ANSWER_QUIZ":
        return {"intent": "quiz"}

    # 3. LLM-based intent determination
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "intent_determination.txt")
    template = ""
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read().strip()
    else:
        template = "Определи намерение пользователя для вопроса: {question}"

    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    parser = JsonOutputParser(pydantic_object=SupervisorOutput)
    
    chat = client.create_chat(temperature=0)
    
    # Enhance prompt with context
    context = ""
    if quiz_active:
        context += "\n[CONTEXT: User is currently in a QUIZ session]"
    if state.get("interaction_mode") == "ALGOS":
        context += "\n[CONTEXT: User is currently in ALGOLAB solving a problem]"

    res = chat.invoke([
        HumanMessage(content=template.format(question=question) + context + "\n\n" + parser.get_format_instructions())
    ])
    
    try:
        output = parser.parse(res.content)
        intent = output.get("intent", "chat")
    except Exception as e:
        log.error(f"Failed to parse supervisor output: {e}")
        intent = "chat"

    if session:
        await session.notify_ui(
            step="supervisor_done",
            message=f"Глобальный интент: {intent}",
            tool="supervisor",
            meta={"intent": intent}
        )

    # Map supervisor intent to state intent if needed, 
    # but here we use it for routing.
    return {"intent": intent}

async def algo_placeholder_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Placeholder for algorithmic interviews.
    """
    session = config.get("configurable", {}).get("session") if config else None
    msg = "🤖 **Алгоритмические собеседования пока находятся в разработке.**\n\nСкоро вы сможете решать задачи в AlgoLab с поддержкой ИИ-интервьюера. А пока вы можете пройти квиз или задать теоретический вопрос."
    
    if session:
        await session.notify_ui(
            step="algo_placeholder",
            message="Режим AlgoLab в процессе разработки и пока не доступен",
            tool="algo_interviewer",
            level="warn"
        )
    
    return {"final_answer": msg}

async def profile_update_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyzes subgraph results and updates the long-term user profile.
    """
    # For now, this is a placeholder as per Stage 5 plan.
    # It would typically analyze quiz_history or algo results.
    return state

# --- Routing Logic ---

def route_from_supervisor(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "quiz":
        return "quiz"
    if intent == "algo":
        return "algo_placeholder"
    if intent == "search":
        return "search"
    return "chat"

# --- Graph Assembly ---

def build_supervisor_graph():
    builder = StateGraph(AgentState)
    
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("quiz", quiz_graph)
    builder.add_node("chat", chat_graph)
    builder.add_node("search", retrieval_graph)
    builder.add_node("algo_placeholder", algo_placeholder_node)
    builder.add_node("profile_update", profile_update_node)
    
    builder.add_edge(START, "supervisor")
    
    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "quiz": "quiz",
            "chat": "chat",
            "search": "search",
            "algo_placeholder": "algo_placeholder"
        }
    )
    
    builder.add_edge("quiz", "profile_update")
    builder.add_edge("chat", "profile_update")
    builder.add_edge("search", "profile_update")
    builder.add_edge("algo_placeholder", "profile_update")
    
    builder.add_edge("profile_update", END)
    
    return builder.compile()

supervisor_graph = build_supervisor_graph()