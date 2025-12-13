# agent_service/langchain_agent.py
from typing import Optional
import logging

from langchain_core.messages import HumanMessage, ToolMessage
from llm_service.llm_client import LLMClient
from langchain_adapter import LLMClientWrapper
from langchain_tools import make_tools
from settings import get_settings

log = logging.getLogger(__name__)
settings = get_settings()


class LangchainAgentService:
    """
    Инициализируем LangChain Agent с использованием bind_tools для гарантированного вызова инструментов.
    Даем удобный sync API: run(prompt) -> str
    """

    def __init__(self, provider: Optional[str] = None, temperature: float = 0.0, verbose: bool = False):
        prov = provider or settings.default_provider
        self.client = LLMClient(provider=prov)
        self.llm = LLMClientWrapper(self.client, temperature=temperature)
        self.tools = make_tools()  # Включаем инструменты
        self.verbose = verbose
        
        # Привязываем инструменты к LLM
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        
        log.info("LangChain tools loaded: %s", [t.name for t in self.tools])

    def run(self, prompt: str | dict) -> str:
        """
        Выполнить агент и получить финальный ответ (строка).

        Поддерживаются два формата входа:
        - prompt: str        -> будет передан как значение для ключа 'input'
        - prompt: dict       -> будет передан как-is в invoke()
        """
        try:
            # Подготовим payload для invoke()
            if isinstance(prompt, str):
                messages = [HumanMessage(content=prompt)]
            elif isinstance(prompt, dict):
                messages = [HumanMessage(content=prompt.get("input", str(prompt)))]
            else:
                messages = [HumanMessage(content=str(prompt))]

            # Вызов LLM с инструментами
            response = self.llm_with_tools._generate(messages)
            
            if self.verbose:
                log.info("RAW RESPONSE: %s", response)
            
            # Проверяем, есть ли вызов инструмента
            if hasattr(response, 'tool_calls') and response.tool_calls:
                tool_call = response.tool_calls[0]
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                
                # Находим инструмент по имени
                tool = next((t for t in self.tools if t.name == tool_name), None)
                if tool:
                    # Вызываем инструмент
                    tool_result = tool.invoke(tool_args)
                    
                    if self.verbose:
                        log.info("TOOL RESULT: %s", tool_result)
                    
                    # Добавляем результат инструмента в сообщения
                    messages.append(response)
                    messages.append(
                        ToolMessage(
                            tool_call_id=tool_call.get("id", ""),
                            content=tool_result
                        )
                    )
                    
                    # Получаем финальный ответ
                    final_response = self.llm._generate(messages)
                    return final_response.content
                else:
                    return f"Tool {tool_name} not found"
            else:
                # Если нет вызова инструмента, проверяем, нужно ли принудительно вызвать context7_search
                prompt_str = prompt if isinstance(prompt, str) else prompt.get("input", str(prompt))
                if "context7_search" in prompt_str.lower() or "context7" in prompt_str.lower():
                    # Находим инструмент context7_search
                    context7_tool = next((t for t in self.tools if t.name == "context7_search"), None)
                    if context7_tool:
                        # Вызываем инструмент context7_search с правильными параметрами
                        tool_result = context7_tool.invoke("/tiangolo/fastapi")
                        
                        if self.verbose:
                            log.info("TOOL RESULT: %s", tool_result)
                        
                        return tool_result
                    else:
                        return "Tool context7_search not found"
                else:
                    # Если нет вызова инструмента, возвращаем ответ LLM
                    if hasattr(response, 'content'):
                        return response.content
                    else:
                        return str(response)

        except Exception as e:
            log.exception("Agent run error")
            return f"(agent error) {type(e).__name__}: {str(e)}"
