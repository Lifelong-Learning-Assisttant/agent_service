# agent_service/langchain_tools.py
from typing import Dict, Any
import httpx
import logging

from langchain.tools import Tool
from settings import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


def _post_json(url: str, payload: Dict[str, Any], timeout: int):
    with httpx.Client(timeout=timeout) as c:
        r = c.post(url, json=payload)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"text": r.text}


def context7_sync(query: str) -> str:
    """Синхронная обёртка для Context7 MCP."""
    url = settings.context7_url
    if not url:
        log.warning("Context7 not configured; returning mock")
        return f"(Context7 mock) {query[:300]}"
    try:
        log.info(f"Using Context7 tool with query: {query}")
        data = _post_json(str(url), {"q": query}, timeout=settings.http_timeout_s)
        if isinstance(data, dict):
            if data.get("summary"):
                return f"(Context7) {data['summary']}"
            items = data.get("items") or data.get("results") or []
            if items:
                snippets = []
                for it in items[:3]:
                    if isinstance(it, dict):
                        snippets.append(it.get("snippet") or it.get("text") or str(it))
                    else:
                        snippets.append(str(it))
                return "(Context7)\n\n" + "\n\n".join(snippets)
        return "(Context7) " + str(data)[:1000]
    except Exception as e:
        log.exception("context7_sync error")
        return f"(Context7 error) {type(e).__name__}: {str(e)[:400]}"


def tavily_sync(query: str) -> str:
    """Синхронная обёртка для Tavily search MCP."""
    url = settings.tavily_url
    if not url:
        log.warning("Tavily not configured; returning mock")
        return f"(Tavily mock) {query[:300]}"
    try:
        log.info(f"Using Tavily tool with query: {query}")
        data = _post_json(str(url), {"query": query}, timeout=settings.http_timeout_s)
        if isinstance(data, dict) and data.get("results"):
            res = data.get("results")[:3]
            return "(Tavily)\n\n" + "\n\n".join([r.get("snippet") if isinstance(r, dict) else str(r) for r in res])
        return "(Tavily) " + str(data)[:1000]
    except Exception as e:
        log.exception("tavily_sync error")
        return f"(Tavily error) {type(e).__name__}: {str(e)[:400]}"


def make_tools() -> list:
    """
    Возвращает список langchain.tools.Tool, готовых к использованию AgentExecutor'ом.
    """
    tools = [
        Tool(
            name="context7",
            func=context7_sync,
            description="Search in Context7 MCP. Input: free-text query. Returns short context snippets."
        ),
        Tool(
            name="tavily",
            func=tavily_sync,
            description="Search in Tavily MCP. Input: free-text query. Returns search snippets."
        ),
    ]
    return tools
