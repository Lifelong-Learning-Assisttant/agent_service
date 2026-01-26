"""
Инструменты для генерации и оценки квизов.
"""
import logging
import httpx
import json
from typing import Dict, Any, List
from settings import get_settings

log = logging.getLogger(__name__)

async def generate_exam_async(markdown_content: str, config: Dict[str, Any] = None) -> str:
    settings = get_settings()
    test_generator_service_url = settings.test_generator_service_url
    if not test_generator_service_url:
        return json.dumps({"error": "Test generator service not configured"})
    try:
        payload = {"markdown_content": markdown_content, "config": config}
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            response = await client.post(f"{test_generator_service_url}/api/generate", json=payload)
            response.raise_for_status()
            return json.dumps(response.json(), ensure_ascii=False)
    except Exception as e:
        log.error(f"Test generator failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

async def grade_exam_async(exam_id: str, answers: List[Dict[str, Any]]) -> str:
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