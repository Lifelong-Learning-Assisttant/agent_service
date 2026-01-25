"""
Инструменты LangChain для подграфа поиска (Retrieval Subgraph).
"""

from typing import Dict, Any, List, Optional
import logging
import httpx
import json
import os
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
    """Асинхронно выполняет поиск документов через RAG сервис."""
    settings = get_settings()
    rag_service_url = settings.rag_service_url
    if not rag_service_url:
        log.warning("RAG service not configured")
        return json.dumps({"error": "RAG service not configured"})
    
    try:
        payload = {"query": query, "top_k": top_k, "use_hyde": use_hyde}
        log.info(f"Async calling RAG search service at {rag_service_url}/search")
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{rag_service_url}/search", json=payload)
            response.raise_for_status()
            result = response.json()
            return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        log.error(f"RAG search failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

async def tavily_search_async(query: str, max_results: int = 5) -> str:
    """Асинхронно выполняет поиск в интернете через Tavily API."""
    settings = get_settings()
    tavily_api_key = settings.tavily_api_key
    if not tavily_api_key:
        log.warning("Tavily API key not found")
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
    """Асинхронно разрешает название библиотеки в Context7 ID."""
    if not library_name: return None
    name_clean = library_name.lower().strip()
    
    if name_clean in ML_LIBRARIES_MAP:
        return ML_LIBRARIES_MAP[name_clean]
        
    settings = get_settings()
    context7_api_key = settings.context7_api_key
    if not context7_api_key: return None
        
    try:
        url = "https://context7.com/api/v2/libs/search"
        headers = {"Authorization": f"Bearer {context7_api_key.get_secret_value()}"}
        params = {"libraryName": library_name, "query": query}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            if results: return results[0].get("id")
    except Exception as e:
        log.error(f"Library resolution failed: {e}")
    return None

async def context7_docs_async(query: str, library_id: str) -> str:
    """Асинхронно запрашивает документацию через Context7 (API v2)."""
    settings = get_settings()
    context7_api_key = settings.context7_api_key
    if not context7_api_key: return json.dumps([])

    try:
        url = "https://context7.com/api/v2/context"
        headers = {"Authorization": f"Bearer {context7_api_key.get_secret_value()}"}
        params = {"libraryId": library_id, "query": query, "type": "json"}
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            result = response.json()
            docs = []
            for info in result.get("infoSnippets", []):
                docs.append({
                    "content": f"### {info.get('breadcrumb', '')}\n{info.get('content', '')}",
                    "url": f"https://context7.com{library_id}/{info.get('pageId', '')}"
                })
            for code_item in result.get("codeSnippets", []):
                code_content = "".join([f"```{c.get('language', 'python')}\n{c.get('code', '')}\n```\n" for c in code_item.get("codeList", [])])
                docs.append({
                    "content": f"### {code_item.get('codeTitle', '')}\n{code_item.get('codeDescription', '')}\n{code_content}",
                    "url": f"https://context7.com{library_id}/{code_item.get('codeId', '')}"
                })
            return json.dumps(docs, ensure_ascii=False)
    except Exception as e:
        log.error(f"Context7 search failed: {e}")
        return json.dumps([], ensure_ascii=False)