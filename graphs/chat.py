import logging
import os
from typing import Dict, List, Any, Optional, Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from state import AgentState
from graphs.retrieval import retrieval_graph
from llm_service.llm_client import LLMClient
from settings import get_settings

log = logging.getLogger(__name__)

# --- Models for Structured Output ---

class ChatRouterOutput(BaseModel):
    """Output of the chat router."""
    classification: Literal["general", "technical"] = Field(
        description="Classification of the user's message: 'general' (chitchat, greetings) or 'technical' (questions about ML/DL/Algorithms)"
    )
    reasoning: str = Field(description="Brief explanation of the classification")

# --- Nodes ---

async def chat_router_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Classifies the user message as 'general' or 'technical'.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(
            step="chat_router",
            message="Классификация запроса...",
            tool="chat_router"
        )

    question = state.get("question", "")
    
    prompt = (
        "Ты — экспертный маршрутизатор диалога. Твоя задача — определить тип сообщения пользователя.\n\n"
        "КАТЕГОРИИ:\n"
        "1. 'general': Приветствия, болтовня, общие вопросы не по теме ML/DL, благодарности.\n"
        "2. 'technical': Вопросы по машинному обучению, нейросетям, алгоритмам, математике в ML.\n\n"
        f"Сообщение: {question}\n\n"
        "Верни JSON с полями 'classification' и 'reasoning'."
    )

    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    parser = JsonOutputParser(pydantic_object=ChatRouterOutput)
    
    chat = client.create_chat(temperature=0)
    res = chat.invoke([
        HumanMessage(content=prompt + "\n\n" + parser.get_format_instructions())
    ])
    
    try:
        output = parser.parse(res.content)
        classification = output.get("classification", "general")
    except Exception as e:
        log.error(f"Failed to parse chat router output: {e}")
        classification = "general"

    if session:
        await session.notify_ui(
            step="chat_router_done",
            message=f"Тип запроса: {classification}",
            tool="chat_router",
            meta={"classification": classification}
        )

    return {"intent": "general" if classification == "general" else "rag_answer"}

async def direct_answer_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Generates a quick response for chitchat or general questions.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(step="direct_answer", message="Подготовка быстрого ответа...", tool="chat")

    # Load direct answer prompt
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "direct_answer.txt")
    system_prompt = "Ты — дружелюбный ассистент-эксперт."
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()

    messages = [SystemMessage(content=system_prompt)]
    # Add conversation history (last 5 messages for context)
    history = state.get("messages", [])[-5:]
    messages.extend(history)
    
    # If the last message is not the current question, add it
    if not history or history[-1].content != state.get("question"):
        messages.append(HumanMessage(content=state.get("question", "")))

    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    chat = client.create_chat(temperature=0.7)
    res = chat.invoke(messages)
    
    return {"final_answer": res.content}

async def full_answer_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Formulates a detailed answer based on retrieved materials.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(step="full_answer", message="Формирование подробного ответа...", tool="chat")

    material = state.get("prepared_material", "Информация не найдена.")
    docs = state.get("documents", [])
    
    # Load system prompt for formatting rules (LaTeX)
    sys_prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.txt")
    system_prompt = ""
    if os.path.exists(sys_prompt_path):
        with open(sys_prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()

    prompt = (
        f"{system_prompt}\n\n"
        "Используя подготовленный материал ниже, ответь на вопрос пользователя. "
        "Обязательно соблюдай правила форматирования LaTeX ($...$ и $$...$$).\n\n"
        f"МАТЕРИАЛ:\n{material}\n\n"
        f"ВОПРОС: {state.get('question')}"
    )
    
    # If using gemini-3-flash-preview, we can't use temperature < 0.3 sometimes?
    # Actually, let's keep temperature low for factual answers.
    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    chat = client.create_chat(temperature=0.3)
    
    # Retry logic for LLM call if it fails
    try:
        res = chat.invoke([HumanMessage(content=prompt)])
        final_answer = res.content
    except Exception as e:
        log.error(f"LLM generation failed in full_answer_node: {e}")
        final_answer = "Извините, произошла ошибка при генерации ответа. Попробуйте еще раз."

    
    # Add sources if available
    if docs:
        sources_list = []
        seen_sources = set()
        for doc in docs:
            src = doc.get("source")
            # Handle non-hashable source types (like dicts)
            if isinstance(src, dict):
                src = str(src.get("url") or src.get("title") or str(src))
            
            if src and isinstance(src, str) and src not in seen_sources:
                sources_list.append(src)
                seen_sources.add(src)
        
        if sources_list:
            final_answer += "\n\n**Источники:**\n" + "\n".join([f"- {s}" for s in sources_list])

    return {"final_answer": final_answer}

# --- Router Logic ---

def route_chat(state: AgentState) -> Literal["general", "technical"]:
    """Determines which branch to take in the chat graph."""
    intent = state.get("intent")
    if intent == "rag_answer":
        return "technical"
    return "general"

# --- Graph Assembly ---

def build_chat_graph():
    builder = StateGraph(AgentState)
    
    builder.add_node("chat_router", chat_router_node)
    builder.add_node("direct_answer", direct_answer_node)
    builder.add_node("retrieval", retrieval_graph)
    builder.add_node("full_answer", full_answer_node)
    
    builder.add_edge(START, "chat_router")
    
    builder.add_conditional_edges(
        "chat_router",
        route_chat,
        {
            "general": "direct_answer",
            "technical": "retrieval"
        }
    )
    
    builder.add_edge("direct_answer", END)
    builder.add_edge("retrieval", "full_answer")
    builder.add_edge("full_answer", END)
    
    return builder.compile()

chat_graph = build_chat_graph()