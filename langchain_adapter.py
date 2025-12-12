# agent_service/langchain_adapter.py
from typing import Optional, List, Mapping, Any
from langchain.llms.base import LLM
from llm_service.llm_client import LLMClient


class LLMClientWrapper(LLM):
    """
    Лёгкий адаптер LangChain -> ваш LLMClient.
    LangChain вызывает _call, мы делегируем в LLMClient.generate.
    """

    def __init__(self, client: LLMClient, temperature: float = 0.2):
        self.client = client
        self.temperature = temperature

    @property
    def _llm_type(self) -> str:
        return "custom_llm_client"

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        # generate возвращает список строк
        out = self.client.generate([prompt], temperature=self.temperature)[0]
        return out or ""

    def _identifying_params(self) -> Mapping[str, Any]:
        return {"provider": getattr(self.client, "provider", None), "temperature": self.temperature}
