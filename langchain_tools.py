# agent_service/langchain_tools.py
"""
Инструменты LangChain для работы с MCP серверами.
Использует лучшие практики для интеграции с Tavily MCP через HTTP.
"""

from typing import Dict, Any, List
import logging
import httpx
import json
from langchain.tools import Tool
from settings import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


def _post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """Отправляет JSON запрос и возвращает ответ."""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error: {e}")
        return {"error": f"HTTP {e.response.status_code}: {str(e)}"}
    except Exception as e:
        log.error(f"Request failed: {e}")
        return {"error": str(e)}


def addition_service(a: float, b: float) -> float:
    """
    Вызывает сервис сложения через FastAPI.
    
    Args:
        a: Первое слагаемое
        b: Второе слагаемое
        
    Returns:
        Результат сложения
    """
    addition_service_url = settings.addition_service_url
    log.info(f"Addition service tool called with a={a}, b={b}")
    
    if not addition_service_url:
        log.warning("Addition service not configured; performing local calculation")
        return a + b
    
    try:
        payload = {"a": a, "b": b}
        log.info(f"Calling addition service at {addition_service_url} with payload: {payload}")
        
        with httpx.Client(timeout=settings.http_timeout_s) as client:
            response = client.post(f"{addition_service_url}/add", json=payload)
            response.raise_for_status()
            result = response.json()
         
        if "result" in result:
            final_result = result["result"]
            log.info(f"Addition service returned result: {final_result}")
            return final_result
        else:
            log.error(f"Unexpected response format from addition service: {result}")
            return a + b  # Fallback to local calculation
         
    except Exception as e:
        log.error(f"Addition service call failed: {e}")
        log.info(f"Falling back to local calculation: {a} + {b} = {a + b}")
        return a + b  # Fallback to local calculation


def rag_search(query: str, top_k: int = 5, use_hyde: bool = False) -> str:
    """
    Выполняет поиск документов через RAG сервис.
    
    Args:
        query: Поисковый запрос
        top_k: Количество результатов (по умолчанию 5)
        use_hyde: Использовать HyDE для улучшения поиска (по умолчанию False)
        
    Returns:
        Результаты поиска в формате JSON
    """
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
        log.info(f"Calling RAG search service at {rag_service_url}/search with payload: {payload}")
        
        result = _post_json(f"{rag_service_url}/search", payload, settings.http_timeout_s)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        log.error(f"RAG search service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def rag_generate(query: str, top_k: int = 5, temperature: float = 0.7, use_hyde: bool = False) -> str:
    """
    Генерирует ответ на вопрос через RAG сервис.
    
    Args:
        query: Вопрос пользователя
        top_k: Количество документов для контекста (по умолчанию 5)
        temperature: Температура генерации (по умолчанию 0.7)
        use_hyde: Использовать HyDE для улучшения поиска (по умолчанию False)
        
    Returns:
        Сгенерированный ответ в формате JSON
    """
    rag_service_url = settings.rag_service_url
    if not rag_service_url:
        log.warning("RAG service not configured")
        return json.dumps({"error": "RAG service not configured"})
    
    try:
        payload = {
            "query": query,
            "top_k": top_k,
            "temperature": temperature,
            "use_hyde": use_hyde
        }
        log.info(f"Calling RAG generate service at {rag_service_url}/rag with payload: {payload}")
        
        result = _post_json(f"{rag_service_url}/rag", payload, settings.http_timeout_s)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        log.error(f"RAG generate service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def make_tools() -> List[Tool]:
    """
    Создает список инструментов LangChain для использования в агентах.
    Следует лучшим практикам для MCP инструментов.
    """
    tools = [
        Tool(
            name="addition_service",
            func=addition_service,
            description="Adds two numbers using the addition service. Input should be two numbers a and b. Returns the sum of a and b."
        ),
        Tool(
            name="rag_search",
            func=rag_search,
            description="Searches for relevant documents using the RAG service. Input should be a query string and optional parameters top_k and use_hyde. Returns search results as JSON."
        ),
        Tool(
            name="rag_generate",
            func=rag_generate,
            description="Generates an answer to a question using the RAG service. Input should be a query string and optional parameters top_k, temperature, and use_hyde. Returns generated answer as JSON."
        ),
    ]
    return tools
