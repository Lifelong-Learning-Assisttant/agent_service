# agent_service/langchain_adapter.py
from typing import Optional, List, Mapping, Any, Union
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from llm_service.llm_client import LLMClient


class LLMClientWrapper:
    """
    Лёгкий адаптер LangChain -> ваш LLMClient.
    Поддерживает bind_tools для вызова инструментов.
    """

    def __init__(self, client: LLMClient, temperature: float = 0.2, **kwargs):
        self.client = client
        self.temperature = temperature
        self._tools = None

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs) -> Union[str, BaseMessage]:
        # Преобразуем сообщения в строку для LLMClient
        prompt = "\n".join([
            f"{msg.type if hasattr(msg, 'type') else 'Human'}: {msg.content}"
            for msg in messages
        ])
        # generate возвращает список строк
        out = self.client.generate([prompt], temperature=self.temperature)[0]
        return AIMessage(content=out or "")

    def bind_tools(self, tools: List[BaseTool], **kwargs) -> "LLMClientWrapper":
        """Привязываем инструменты к модели."""
        self._tools = tools
        return self
