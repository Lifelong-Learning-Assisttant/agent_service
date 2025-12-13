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


class TavilyMCPTool:
    """
    Инструмент для работы с Tavily MCP сервером через HTTP.
    Следует лучшим практикам для интеграции MCP tools.
    """
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or settings.tavily_url
        if not self.base_url:
            raise ValueError("Tavily URL not configured")
    
    def search(self, query: str, search_depth: str = "basic", 
               topic: str = "general", max_results: int = 5) -> str:
        """
        Выполняет поиск через Tavily MCP сервер.
        
        Args:
            query: Поисковый запрос
            search_depth: Глубина поиска (basic/advanced)
            topic: Тема поиска
            max_results: Максимальное количество результатов
            
        Returns:
            Строка с результатами поиска
        """
        # Создаем MCP запрос согласно спецификации
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tavily-search",
                "arguments": {
                    "query": query,
                    "search_depth": search_depth,
                    "topic": topic,
                    "max_results": max_results
                }
            }
        }
        
        log.info(f"Sending MCP request to {self.base_url}")
        
        # Отправляем запрос
        response = _post_json(self.base_url, message, settings.http_timeout_s)
        
        # Обрабатываем ответ
        if "error" in response:
            return f"(Tavily error) {response['error'][:400]}"
        
        if isinstance(response, dict) and response.get("result"):
            results = response.get("result")
            if isinstance(results, list):
                # Форматируем результаты согласно лучшим практикам
                formatted_results = []
                for i, result in enumerate(results[:3], 1):
                    if isinstance(result, dict):
                        title = result.get("title", f"Result {i}")
                        snippet = result.get("snippet", "")
                        url = result.get("url", "")
                        formatted_results.append(f"{title}\n{url}\n{snippet}")
                    else:
                        formatted_results.append(str(result))
                return "(Tavily search results)\n\n" + "\n\n---\n\n".join(formatted_results)
            elif isinstance(results, dict):
                return "(Tavily)\n\n" + str(results)
        
        return "(Tavily) " + str(response)[:1000]


# Глобальный экземпляр инструмента
tavily_tool = TavilyMCPTool()


def tavily_search(query: str) -> str:
    """
    Функция для использования в LangChain инструментах.
    Выполняет поиск через Tavily MCP сервер.
    """
    return tavily_tool.search(query)


def context7_search(query: str, library_name: str = None) -> str:
    """
    Context7 MCP search using get-library-docs method directly.
    """
    base_url = settings.context7_url
    if not base_url:
        log.warning("Context7 not configured; returning mock")
        return f"(Context7 mock) {query[:300]}"
    
    log.info(f"Context7 search called with query: {query}, library: {library_name}")

    # Normalize base URL - ensure it ends with /mcp
    if not base_url.endswith("/mcp"):
        if base_url.endswith("/"):
            base_url = base_url + "mcp"
        else:
            base_url = base_url + "/mcp"

    log.info(f"Connecting to Context7 MCP at {base_url}")

    # Normalize library ID - remove leading slash if present
    library_id = library_name or query
    if library_id.startswith("/"):
        library_id = library_id[1:]

    # Use direct POST to /mcp with proper authorization
    try:
        # Direct call to get-library-docs
        docs_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get-library-docs",
                "arguments": {
                    "context7CompatibleLibraryID": library_id,
                    "mode": "code",
                    "topic": query
                }
            }
        }

        log.info(f"Context7: getting docs for library {library_id}")
        with httpx.Client(timeout=settings.http_timeout_s) as client:
            headers = {
                "Accept": "application/json, text/event-stream"
            }
            # Add Authorization header if API key is available
            if settings.context7_api_key and settings.context7_api_key.get_secret_value():
                headers["Authorization"] = f"Bearer {settings.context7_api_key.get_secret_value()}"
            response = client.post(base_url, json=docs_msg, headers=headers)
            response.raise_for_status()
            docs_result = response.json()

        if "error" in docs_result:
            error_msg = docs_result.get('error', 'Unknown error')
            if isinstance(error_msg, dict):
                error_msg = error_msg.get('message', str(error_msg))
            return f"(Context7 error) {str(error_msg)[:400]}"

        if isinstance(docs_result, dict) and docs_result.get("result"):
            results = docs_result.get("result")
            if isinstance(results, dict):
                content = results.get("content", [])
                if isinstance(content, list):
                    text_parts = [item.get("text", "") for item in content if item.get("type") == "text"]
                    return "\n\n".join(text_parts)
                return str(results)
            elif isinstance(results, str):
                return f"(Context7) {results}"

        return f"(Context7) {str(docs_result)[:1000]}"

    except Exception as e:
        log.error("Context7 request failed: %s", e)
        return f"(Context7 error) {str(e)}"


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


def make_tools() -> List[Tool]:
    """
    Создает список инструментов LangChain для использования в агентах.
    Следует лучшим практикам для MCP инструментов.
    """
    tools = [
        Tool(
            name="tavily_search",
            func=tavily_search,
            description="Search the web using Tavily MCP server. Input should be a search query. Returns relevant search results."
        ),
        Tool(
            name="context7_search",
            func=context7_search,
            description="Useful for searching documentation and code examples in libraries. Input should be a query and optional library name. Returns relevant documentation snippets."
        ),
        Tool(
            name="addition_service",
            func=addition_service,
            description="Adds two numbers using the addition service. Input should be two numbers a and b. Returns the sum of a and b."
        ),
    ]
    return tools
