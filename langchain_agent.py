# agent_service/langchain_agent.py
from typing import Optional
import logging

from langchain.agents import AgentExecutor, create_react_agent
from langchain.agents.agent import Agent
from langchain.prompts import PromptTemplate
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
        self.tools = make_tools()  # Включаем инструменты
        # self.tools = []  # Пустой список инструментов
        # Agent: Zero-shot REACT (reasoning + tools)
        # with open('prompts/agent_prompt.txt', 'r', encoding='utf-8') as file:
        #     prompt_template = file.read()
        #
        # prompt = PromptTemplate.from_template(prompt_template)
        
        # Используем простой промпт
        with open('prompts/simple_prompt.txt', 'r', encoding='utf-8') as file:
            prompt_template = file.read()
                  
        prompt = PromptTemplate.from_template(prompt_template)
        self.agent = create_react_agent(self.llm, self.tools, prompt)
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=verbose,
            handle_parsing_errors=True,
            max_iterations=50,  # Увеличиваем лимит итераций
            max_execution_time=None  # Убираем лимит по времени
        )

    def run(self, prompt: str | dict) -> str:
        """
        Выполнить агент и получить финальный ответ (строка).

        Поддерживаются два формата входа:
        - prompt: str        -> будет передан как значение для ключа 'input'
        - prompt: dict       -> будет передан как-is в invoke()

        Используем .invoke(), потому что .run() в LangChain требует ровно одного output_key,
        а у нас этого гарантировать нельзя (зависит от версии/конфигурации).
        """
        try:
            # Подготовим payload для invoke()
            if isinstance(prompt, str):
                payload = {"input": prompt}
            elif isinstance(prompt, dict):
                payload = prompt
            else:
                payload = {"input": str(prompt)}

            # Вызов агента (invoke обычно возвращает dict или объект с полями)
            result = self.agent_executor.invoke(payload)

            # Результат может быть:
            # - строкой
            # - dict с одним/несколькими ключами
            # - объект с атрибутом content / text
            if isinstance(result, str):
                return result

            if isinstance(result, dict):
                # Часто ключ называется 'output' или 'final_answer' либо 'answer'
                for preferred in ("output", "final_answer", "answer", "result"):
                    if preferred in result:
                        return str(result[preferred] or "")

                # Если в dict ровно одно значение — вернём его
                if len(result) == 1:
                    return str(next(iter(result.values())) or "")

                # Иначе преобразуем dict в читабельную строку
                return str(result)

            # Иногда LangChain возвращает объект с content/text
            content = getattr(result, "content", None) or getattr(result, "text", None)
            if content:
                return str(content)

            # Фоллбек — строковое представление результата
            return str(result)

        except Exception as e:
            log.exception("Agent run error")
            return f"(agent error) {type(e).__name__}: {str(e)}"
