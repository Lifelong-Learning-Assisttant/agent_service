# agent_service/langchain_agent.py
from typing import Optional
import logging

from langchain.agents import initialize_agent, AgentType
from langchain.tools import Tool
from llm_service.llm_client import LLMClient
from agent_service.langchain_adapter import LLMClientWrapper
from agent_service.langchain_tools import make_tools
from agent_service.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


class LangchainAgentService:
    """
    Инициализируем LangChain Agent (AgentExecutor) с вашими MCP-инструментами.
    Даем удобный sync API: run(prompt) -> str
    """

    def __init__(self, provider: Optional[str] = None, temperature: float = 0.2, verbose: bool = False):
        prov = provider or settings.default_provider
        self.client = LLMClient(provider=prov)
        self.llm = LLMClientWrapper(self.client, temperature=temperature)
        self.tools = make_tools()
        # Agent: Zero-shot REACT (reasoning + tools)
        self.agent = initialize_agent(self.tools, self.llm, agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION, verbose=verbose)

    def run(self, prompt: str) -> str:
        """
        Выполнить агент, получить финальный ответ (строка).
        (AgentExecutor.run обычно синхронен.)
        """
        try:
            return self.agent.run(prompt)
        except Exception as e:
            log.exception("Agent run error")
            # возвращаем понятную строку, чтобы UI не крашился
            return f"(agent error) {type(e).__name__}: {str(e)}"
