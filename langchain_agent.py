# agent_service/langchain_agent.py
from typing import Optional
import logging

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from llm_service.llm_client import LLMClient
from langchain_adapter import LLMClientWrapper
from langchain_tools import make_tools
from settings import get_settings

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
        with open('prompts/agent_prompt.txt', 'r', encoding='utf-8') as file:
            prompt_template = file.read()
               
        prompt = PromptTemplate.from_template(prompt_template)
        self.agent = create_react_agent(self.llm, self.tools, prompt)
        self.agent_executor = AgentExecutor(agent=self.agent, tools=self.tools, verbose=verbose, handle_parsing_errors=True)

    def run(self, prompt: dict) -> str:
        """
        Выполнить агент, получить финальный ответ (строка).
        (AgentExecutor.run обычно синхронен.)
        """
        try:
            return self.agent_executor.invoke(prompt)
        except Exception as e:
            log.exception("Agent run error")
            # возвращаем понятную строку, чтобы UI не крашился
            return f"(agent error) {type(e).__name__}: {str(e)}"
