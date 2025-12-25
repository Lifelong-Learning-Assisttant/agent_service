# agent_service/langchain_tools.py
"""
Асинхронные инструменты LangChain для работы с MCP серверами.
Использует httpx.AsyncClient для не блокирующих HTTP-запросов.
"""

from typing import Dict, Any, List
import logging
import httpx
import json
from langchain.tools import Tool
from settings import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


async def rag_search_async(query: str, top_k: int = 5, use_hyde: bool = False) -> str:
    """
    Асинхронно выполняет поиск документов через RAG сервис.
    
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
        log.info(f"Async calling RAG search service at {rag_service_url}/search with payload: {payload}")
        
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{rag_service_url}/search", json=payload)
            response.raise_for_status()
            result = response.json()
            return json.dumps(result, ensure_ascii=False)
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error in rag_search_async: {e}")
        return json.dumps({"error": f"HTTP {e.response.status_code}: {str(e)}"}, ensure_ascii=False)
    except Exception as e:
        log.error(f"RAG search async service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def rag_generate_async(query: str, top_k: int = 5, temperature: float = 0.7, use_hyde: bool = False) -> str:
    """
    Асинхронно генерирует ответ на вопрос через RAG сервис.
    
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
        log.info(f"Async calling RAG generate service at {rag_service_url}/rag with payload: {payload}")
        
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{rag_service_url}/rag", json=payload)
            response.raise_for_status()
            result = response.json()
            return json.dumps(result, ensure_ascii=False)
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error in rag_generate_async: {e}")
        return json.dumps({"error": f"HTTP {e.response.status_code}: {str(e)}"}, ensure_ascii=False)
    except Exception as e:
        log.error(f"RAG generate async service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def generate_exam_async(markdown_content: str, config: Dict[str, Any] = None) -> str:
    """
    Асинхронно генерирует экзамен через сервис test_generator.
    
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
        log.info(f"Async calling test generator service at {test_generator_service_url}/api/generate with payload: {payload}")
        
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{test_generator_service_url}/api/generate", json=payload)
            response.raise_for_status()
            result = response.json()
            return json.dumps(result, ensure_ascii=False)
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error in generate_exam_async: {e}")
        return json.dumps({"error": f"HTTP {e.response.status_code}: {str(e)}"}, ensure_ascii=False)
    except Exception as e:
        log.error(f"Test generator async service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def grade_exam_async(exam_id: str, answers: List[Dict[str, Any]]) -> str:
    """
    Асинхронно оценивает ответы на экзамен через сервис test_generator.
    
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
        log.info(f"Async calling test generator grade service at {test_generator_service_url}/api/grade with payload: {payload}")
        
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{test_generator_service_url}/api/grade", json=payload)
            response.raise_for_status()
            result = response.json()
            return json.dumps(result, ensure_ascii=False)
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error in grade_exam_async: {e}")
        return json.dumps({"error": f"HTTP {e.response.status_code}: {str(e)}"}, ensure_ascii=False)
    except Exception as e:
        log.error(f"Test generator grade async service call failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def make_async_tools() -> List[Tool]:
    """
    Создает список асинхронных инструментов LangChain для использования в агентах.
    Инструменты используют async-функции для не блокирующих вызовов.
    """
    tools = [
        Tool(
            name="rag_search",
            func=rag_search_async,
            description="Асинхронный поиск документов через RAG сервис. Вход: query, top_k, use_hyde. Возвращает результаты поиска в JSON."
        ),
        Tool(
            name="rag_generate",
            func=rag_generate_async,
            description="Асинхронная генерация ответа через RAG сервис. Вход: query, top_k, temperature, use_hyde. Возвращает сгенерированный ответ в JSON."
        ),
        Tool(
            name="generate_exam",
            func=generate_exam_async,
            description="Асинхронная генерация экзамена из Markdown контента. Вход: markdown_content, config. Возвращает экзамен в JSON."
        ),
        Tool(
            name="grade_exam",
            func=grade_exam_async,
            description="Асинхронная оценка ответов на экзамен. Вход: exam_id, answers. Возвращает результаты оценки в JSON."
        ),
    ]
    return tools
