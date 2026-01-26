# agent_service/langchain_tools.py
"""
Асинхронные инструменты LangChain для работы с внешними сервисами (RAG, Tavily, Context7).
Использует httpx.AsyncClient для не блокирующих HTTP-запросов.
"""

from typing import Dict, Any, List, Optional
import logging
import httpx
import json
import os
import aiofiles
from langchain.tools import Tool, tool
from settings import get_settings

log = logging.getLogger(__name__)

# Маппинг популярных библиотек для мгновенного резолвинга
ML_LIBRARIES_MAP = {
    "pytorch": "/pytorch/pytorch",
    "torch": "/pytorch/pytorch",
    "scikit-learn": "/scikit-learn/scikit-learn",
    "sklearn": "/scikit-learn/scikit-learn",
    "pandas": "/pandas-dev/pandas",
    "numpy": "/numpy/numpy",
    "matplotlib": "/matplotlib/matplotlib",
    "seaborn": "/mwaskom/seaborn",
    "tensorflow": "/tensorflow/tensorflow",
    "keras": "/keras-team/keras",
    "transformers": "/huggingface/transformers",
    "hf": "/huggingface/transformers",
    "diffusers": "/huggingface/diffusers",
    "datasets": "/huggingface/datasets",
    "langchain": "/langchain-ai/langchain",
    "langgraph": "/langchain-ai/langgraph",
    "fastapi": "/tiangolo/fastapi",
    "pydantic": "/pydantic/pydantic",
    "polars": "/pola-rs/polars",
    "xgboost": "/dmlc/xgboost",
    "lightgbm": "/microsoft/lightgbm",
    "catboost": "/catboost/catboost"
}


async def rag_search_async(query: str, top_k: int = 5, use_hyde: bool = False) -> str:
    """
    Асинхронно выполняет поиск документов через RAG сервис.
    """
    settings = get_settings()
    rag_service_url = settings.rag_service_url
    if not rag_service_url:
        log.warning("RAG service not configured")
        return json.dumps({"error": "RAG service not configured"})
    
    try:
        payload = {
            "query": query,
            "top_k": top_k,
            "use_hyde": use_hyde
        }
        log.info(f"Async calling RAG search service at {rag_service_url}/search with payload: {payload}")
        
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{rag_service_url}/search", json=payload)
            response.raise_for_status()
            result = response.json()
            return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        log.error(f"RAG search async service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def tavily_search_async(query: str, max_results: int = 5) -> str:
    """
    Асинхронно выполняет поиск в интернете через Tavily API.
    """
    settings = get_settings()
    tavily_api_key = settings.tavily_api_key
    
    if not tavily_api_key:
        log.warning("Tavily API key not found in settings")
        return json.dumps({"results": []})

    try:
        payload = {
            "api_key": tavily_api_key.get_secret_value(),
            "query": query,
            "search_depth": "basic",
            "max_results": max_results
        }
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
            response.raise_for_status()
            return json.dumps(response.json(), ensure_ascii=False)
    except Exception as e:
        log.error(f"Tavily search failed: {e}")
        return json.dumps({"results": [], "error": str(e)}, ensure_ascii=False)


async def resolve_library_id_async(library_name: str, query: str = "") -> Optional[str]:
    """
    Асинхронно разрешает название библиотеки в Context7 ID (API v2).
    """
    if not library_name:
        return None
        
    name_clean = library_name.lower().strip()
    
    # 1. Проверяем хардкод (ML_LIBRARIES_MAP)
    if name_clean in ML_LIBRARIES_MAP:
        log.info(f"Library {library_name} resolved via map: {ML_LIBRARIES_MAP[name_clean]}")
        return ML_LIBRARIES_MAP[name_clean]
        
    # 2. Пробуем через API Context7 v2
    settings = get_settings()
    context7_api_key = settings.context7_api_key
    if not context7_api_key:
        return None
        
    try:
        # Эндпоинт v2 для поиска библиотек
        url = "https://context7.com/api/v2/libs/search"
        headers = {"Authorization": f"Bearer {context7_api_key.get_secret_value()}"}
        params = {"libraryName": library_name, "query": query}
        
        log.info(f"Resolving library {library_name} via Context7 v2 API")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            if isinstance(results, list) and len(results) > 0:
                return results[0].get("id")
    except Exception as e:
        log.error(f"Failed to resolve library {library_name}: {e}")
        
    return None


async def context7_docs_async(query: str, library_id: str) -> str:
    """
    Асинхронно запрашивает документацию через Context7 (API v2).
    """
    settings = get_settings()
    context7_api_key = settings.context7_api_key
    
    if not context7_api_key:
        log.warning("Context7 API key not found in settings")
        return json.dumps([])

    try:
        # Используем API v2 /context эндпоинт (GET)
        url = "https://context7.com/api/v2/context"
        headers = {"Authorization": f"Bearer {context7_api_key.get_secret_value()}"}
        params = {
            "libraryId": library_id,
            "query": query,
            "type": "json" # Запрашиваем структурированный JSON
        }
        
        log.info(f"Async calling Context7 v2 (GET) at {url} for library {library_id}")
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            docs = []
            # Обработка информационных сниппетов
            for info in result.get("infoSnippets", []):
                docs.append({
                    "content": f"### {info.get('breadcrumb', '')}\n{info.get('content', '')}",
                    "url": f"https://context7.com{library_id}/{info.get('pageId', '')}"
                })
            
            # Обработка сниппетов кода
            for code_item in result.get("codeSnippets", []):
                code_content = ""
                for c in code_item.get("codeList", []):
                    code_content += f"```{c.get('language', 'python')}\n{c.get('code', '')}\n```\n"
                
                docs.append({
                    "content": f"### {code_item.get('codeTitle', '')}\n{code_item.get('codeDescription', '')}\n{code_content}",
                    "url": f"https://context7.com{library_id}/{code_item.get('codeId', '')}"
                })
            
            return json.dumps(docs, ensure_ascii=False)
    except Exception as e:
        log.error(f"Context7 search failed: {e}")
        return json.dumps([], ensure_ascii=False)


async def generate_exam_async(markdown_content: str, config: Dict[str, Any] = None) -> str:
    """
    Асинхронно генерирует экзамен через сервис test_generator.
    """
    settings = get_settings()
    test_generator_service_url = settings.test_generator_service_url
    if not test_generator_service_url:
        log.warning("Test generator service not configured")
        return json.dumps({"error": "Test generator service not configured"})
    
    try:
        payload = {
            "markdown_content": markdown_content,
            "config": config
        }
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{test_generator_service_url}/api/generate", json=payload)
            response.raise_for_status()
            return json.dumps(response.json(), ensure_ascii=False)
    except Exception as e:
        log.error(f"Test generator failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def grade_exam_async(exam_id: str, answers: List[Dict[str, Any]]) -> str:
    """
    Асинхронно оценивает ответы на экзамен.
    """
    settings = get_settings()
    test_generator_service_url = settings.test_generator_service_url
    if not test_generator_service_url:
        return json.dumps({"error": "Test generator service not configured"})
    
    try:
        payload = {"exam_id": exam_id, "answers": answers}
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{test_generator_service_url}/api/grade", json=payload)
            response.raise_for_status()
            return json.dumps(response.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
async def get_algo_problem_info(problem_id: str) -> str:
    """Возвращает информацию о задаче."""
    base_path = f"../data/algo_problems/{problem_id}"
    try:
        info = {"problem_id": problem_id}
        for filename, key in [("task.md", "task_description"), ("interviewer_note.md", "interviewer_notes")]:
            path = os.path.join(os.path.dirname(__file__), base_path, filename)
            if os.path.exists(path):
                async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
                    info[key] = await f.read()
        return json.dumps(info, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def get_algo_solution(problem_id: str) -> str:
    """Возвращает эталонное решение."""
    path = os.path.join(os.path.dirname(__file__), f"../data/algo_problems/{problem_id}/hidden_solution.py")
    try:
        if os.path.exists(path):
            async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
                return json.dumps({"solution": await f.read()}, ensure_ascii=False)
        return json.dumps({"error": "Solution not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def make_async_tools() -> List[Tool]:
    """Создает список инструментов."""
    return [
        Tool(name="rag_search", func=rag_search_async, description="Поиск в RAG."),
        Tool(name="tavily_search", func=tavily_search_async, description="Поиск в Web."),
        Tool(name="context7_docs", func=context7_docs_async, description="Поиск в документации."),
        Tool(name="generate_exam", func=generate_exam_async, description="Генерация экзамена."),
        Tool(name="grade_exam", func=grade_exam_async, description="Оценка экзамена."),
        Tool(name="get_algo_problem_info", func=get_algo_problem_info, description="Инфо о задаче."),
        Tool(name="get_algo_solution", func=get_algo_solution, description="Решение задачи."),
    ]
