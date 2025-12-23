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


def _get_json(url: str, timeout: int) -> Dict[str, Any]:
    """Отправляет GET запрос и возвращает ответ."""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error: {e}")
        return {"error": f"HTTP {e.response.status_code}: {str(e)}"}
    except Exception as e:
        log.error(f"Request failed: {e}")
        return {"error": str(e)}


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


def generate_exam(markdown_content: str, config: Dict[str, Any] = None) -> str:
    """
    Генерирует экзамен через сервис test_generator.
    
    Args:
        markdown_content: Содержимое Markdown для генерации вопросов
        config: Конфигурация для генерации экзамена
        
    Returns:
        Сгенерированный экзамен в формате JSON
    """
    test_generator_service_url = settings.test_generator_service_url
    if not test_generator_service_url:
        log.warning("Test generator service not configured")
        return json.dumps({"error": "Test generator service not configured"})
    
    try:
        payload = {
            "markdown_content": markdown_content,
            "config": config
        }
        log.info(f"Calling test generator service at {test_generator_service_url}/api/generate with payload: {payload}")
        
        result = _post_json(f"{test_generator_service_url}/api/generate", payload, settings.http_timeout_s)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        log.error(f"Test generator service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def grade_exam(exam_id: str, answers: List[Dict[str, Any]]) -> str:
    """
    Оценивает ответы на экзамен через сервис test_generator.
    
    Args:
        exam_id: Идентификатор экзамена
        answers: Список ответов студента
        
    Returns:
        Результаты оценки в формате JSON
    """
    test_generator_service_url = settings.test_generator_service_url
    if not test_generator_service_url:
        log.warning("Test generator service not configured")
        return json.dumps({"error": "Test generator service not configured"})
    
    try:
        payload = {
            "exam_id": exam_id,
            "answers": answers
        }
        log.info(f"Calling test generator grade service at {test_generator_service_url}/api/grade with payload: {payload}")
        
        result = _post_json(f"{test_generator_service_url}/api/grade", payload, settings.http_timeout_s)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        log.error(f"Test generator grade service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def make_tools() -> List[Tool]:
    """
    Создает список инструментов LangChain для использования в агентах.
    Следует лучшим практикам для MCP инструментов.
    """
    tools = [
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
        Tool(
            name="generate_exam",
            func=generate_exam,
            description="Generates an exam from Markdown content using the test generator service. Input should be markdown_content and optional config. Returns generated exam as JSON."
        ),
        Tool(
            name="grade_exam",
            func=grade_exam,
            description="Grades student answers against exam answer keys using the test generator service. Input should be exam_id and answers. Returns grading results as JSON."
        ),
    ]
    return tools
