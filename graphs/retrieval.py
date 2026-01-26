import json
import logging
import os
from typing import Dict, List, Any, Optional, Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from state import RetrievalState
from tools import rag_search_async, tavily_search_async, context7_docs_async, resolve_library_id_async
from llm_service.llm_client import LLMClient
from settings import get_settings

log = logging.getLogger(__name__)

# --- Models for Structured Output ---

class RetrievalRouterOutput(BaseModel):
    """Output of the retrieval router."""
    selected_sources: List[Literal["rag", "web", "docs"]] = Field(
        description="List of sources to search: 'rag' (Yandex Handbook), 'web' (Tavily/Internet), 'docs' (Context7/Library Docs)"
    )
    reasoning: str = Field(description="Brief explanation of why these sources were chosen")

# --- Nodes ---

async def retrieval_router_node(state: RetrievalState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Analyzes the user's question and decides which retrieval tools to use.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(
            step="retrieval_router",
            message="Анализ источников для поиска знаний...",
            tool="retrieval_router"
        )

    question = state.get("question", "")
    
    # Load prompt for router
    # For now, using a simplified logic or a small prompt
    prompt = (
        "Ты — экспертный маршрутизатор поиска. Твоя задача — определить, какие источники знаний "
        "нужны для ответа на вопрос пользователя.\n"
        "Источники:\n"
        "1. 'rag': Фундаментальные знания по ML/DL (Учебник Яндекса).\n"
        "2. 'web': Свежие новости, тренды, общая информация из интернета.\n"
        "3. 'docs': Документация библиотек, API, примеры кода.\n\n"
        f"Вопрос: {question}\n\n"
        "Верни JSON с полями 'selected_sources' (список строк) и 'reasoning'."
    )

    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    parser = JsonOutputParser(pydantic_object=RetrievalRouterOutput)
    
    chat = client.create_chat(temperature=0)
    res = chat.invoke([
        HumanMessage(content=prompt + "\n\n" + parser.get_format_instructions())
    ])
    
    try:
        output = parser.parse(res.content)
        selected = output.get("selected_sources", ["rag"])
        if not selected:
            selected = ["rag"]
    except Exception as e:
        log.error(f"Failed to parse retrieval router output: {e}")
        selected = ["rag"]

    if session:
        await session.notify_ui(
            step="retrieval_router_done",
            message=f"Выбраны источники: {', '.join(selected)}",
            tool="retrieval_router",
            meta={"selected_sources": selected}
        )

    return {"selected_sources": selected, "raw_results": {}}

async def rag_node(state: RetrievalState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """Retrieves knowledge from Yandex ML Handbook."""
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(step="rag_search", message="Поиск в базе знаний Яндекса...", tool="rag_search")

    query = state.get("question", "")
    res_json = await rag_search_async(query, top_k=5)
    
    try:
        data = json.loads(res_json)
        docs = []
        if isinstance(data, dict) and "documents" in data:
            for i, content in enumerate(data["documents"]):
                docs.append({
                    "content": content,
                    "source": data.get("sources", [])[i] if i < len(data.get("sources", [])) else "Yandex Handbook",
                    "type": "rag"
                })
        return {"raw_results": {"rag": docs}}
    except Exception as e:
        log.error(f"RAG node error: {e}")
        return {"raw_results": {"rag": []}}

async def tavily_node(state: RetrievalState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """Retrieves knowledge from the Web using Tavily."""
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(step="web_search", message="Поиск в интернете (Tavily)...", tool="tavily")

    query = state.get("question", "")
    res_json = await tavily_search_async(query)
    
    try:
        data = json.loads(res_json)
        docs = []
        # Tavily returns a list of results in 'results' field
        if isinstance(data, dict) and "results" in data:
            for item in data["results"]:
                docs.append({
                    "content": item.get("content", ""),
                    "source": item.get("url", "Tavily"),
                    "type": "web"
                })
        return {"raw_results": {"web": docs}}
    except Exception as e:
        log.error(f"Tavily node error: {e}")
        return {"raw_results": {"web": []}}

async def library_resolver_node(state: RetrievalState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Extracts library name from question and resolves it to Context7 ID.
    """
    session = config.get("configurable", {}).get("session") if config else None
    question = state.get("question", "")
    
    # Промпт для извлечения названия библиотеки
    prompt = (
        "Извлеки название основной библиотеки или фреймворка из вопроса пользователя. "
        "Верни ТОЛЬКО название (например, 'pytorch', 'pandas', 'transformers'). "
        "Если библиотек несколько, выбери самую важную. Если ни одной — верни 'none'.\n\n"
        f"Вопрос: {question}"
    )
    
    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    chat = client.create_chat(temperature=0)
    res = chat.invoke([HumanMessage(content=prompt)])
    
    lib_name = res.content.lower().strip().replace("'", "").replace('"', "")
    
    if lib_name == "none":
        return {"library_id": None}
        
    if session:
        await session.notify_ui(
            step="library_resolving",
            message=f"Определена библиотека: {lib_name}",
            tool="resolver"
        )
        
    lib_id = await resolve_library_id_async(lib_name, query=question)
    return {"library_id": lib_id}

async def context7_node(state: RetrievalState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """Retrieves library documentation using Context7."""
    session = config.get("configurable", {}).get("session") if config else None
    
    lib_id = state.get("library_id")
    if not lib_id:
        log.info("No library_id found, skipping Context7 node")
        return {"raw_results": {"docs": []}}

    if session:
        await session.notify_ui(
            step="docs_search",
            message=f"Поиск в документации {lib_id}...",
            tool="context7"
        )

    query = state.get("question", "")
    res_json = await context7_docs_async(query, library_id=lib_id)
    
    try:
        data = json.loads(res_json)
        docs = []
        if isinstance(data, list):
            for item in data:
                # Унифицируем формат контента
                if isinstance(item, dict):
                    content = item.get("content") or item.get("text") or str(item)
                    source = item.get("url") or item.get("source") or f"https://context7.com{lib_id}"
                else:
                    content = str(item)
                    source = f"https://context7.com{lib_id}"
                
                docs.append({
                    "content": content,
                    "source": source,
                    "type": "docs"
                })
        return {"raw_results": {"docs": docs}}
    except Exception as e:
        log.error(f"Context7 node error: {e}")
        return {"raw_results": {"docs": []}}

async def aggregator_node(state: RetrievalState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """Aggregates all raw results into a unified document list."""
    raw_results = state.get("raw_results", {})
    selected_sources = state.get("selected_sources", [])
    all_docs = []
    
    log.info(f"Aggregating results. Selected sources: {selected_sources}. Raw keys: {list(raw_results.keys())}")
    
    for source, docs in raw_results.items():
        # Включаем документы только если источник был выбран роутером
        if source in selected_sources and isinstance(docs, list):
            all_docs.extend(docs)
            
    return {"documents": all_docs}

async def prepare_material_node(state: RetrievalState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """Synthesizes the Golden Source markdown from aggregated documents."""
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(step="prepare_material", message="Синтез учебного материала...", tool="prepare_material")

    docs = state.get("documents", [])
    if not docs:
        return {"prepared_material": "Информация не найдена.", "is_relevant": False}

    # Context construction
    context = ""
    for i, doc in enumerate(docs):
        context += f"--- SOURCE {i+1} ({doc.get('type', 'unknown')}) ---\n{doc.get('content', '')}\n\n"

    # Use LLM to synthesize
    prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "prepare_quiz_material.txt")
    template = ""
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read().strip()
    else:
        template = "Синтезируй ответ на основе чанков:\n{chunks}"

    final_prompt = template.format(chunks=context)
    
    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    chat = client.create_chat(temperature=0)
    res = chat.invoke([HumanMessage(content=final_prompt)])
    
    material = res.content
    is_relevant = len(material) > 50 and "не нашел" not in material.lower()

    return {"prepared_material": material, "is_relevant": is_relevant}

# --- Router Logic ---

def route_retrieval(state: RetrievalState) -> List[str]:
    """Determines which retrieval nodes to run in parallel."""
    return state.get("selected_sources", ["rag"])

# --- Graph Assembly ---

def build_retrieval_graph():
    builder = StateGraph(RetrievalState)
    
    builder.add_node("router", retrieval_router_node)
    builder.add_node("rag", rag_node)
    builder.add_node("web", tavily_node)
    builder.add_node("resolver", library_resolver_node)
    builder.add_node("docs", context7_node)
    builder.add_node("aggregator", aggregator_node)
    builder.add_node("prepare_material", prepare_material_node)
    
    builder.add_edge(START, "router")
    
    # Conditional edges from router to parallel retrieval nodes
    builder.add_conditional_edges(
        "router",
        route_retrieval,
        {
            "rag": "rag",
            "web": "web",
            "docs": "resolver" # Сначала резолвим библиотеку
        }
    )
    
    # All retrieval nodes go to aggregator
    builder.add_edge("rag", "aggregator")
    builder.add_edge("web", "aggregator")
    builder.add_edge("resolver", "docs") # resolver -> docs
    builder.add_edge("docs", "aggregator")
    
    builder.add_edge("aggregator", "prepare_material")
    builder.add_edge("prepare_material", END)
    
    return builder.compile()

retrieval_graph = build_retrieval_graph()