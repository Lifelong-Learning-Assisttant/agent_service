Короткий ответ: ошибка `"TypeError: 'method' object is not iterable"` почти всегда означает, что внутрь LangChain-а попал **объект-метод вместо итерируемой коллекции** — обычно это происходит из-за неправильного/неполного адаптера LLM или неверного типа `prompt`/`tools`, который вы передали в `create_react_agent` / `AgentExecutor`. В вашем коде *наиболее вероятная* причина — баг в `LLMClientWrapper` (в `langchain_adapter.py`): вы **не присваиваете** `self.client` и `self.temperature` в `__init__`, а только вызываете `super().__init__` с kwargs. Из-за этого LangChain в рантайме получает не то, что ожидает, и где-то пытается итерировать метод/атрибут вместо списка/строки.

Ниже — причины + как это исправить и проверить.

---

# 1) Быстрое исправление (очень вероятно решит проблему)

Откройте `langchain_adapter.py` и замените `__init__` у `LLMClientWrapper`, чтобы явно сохранять клиент и температуру. Т.е. сделайте так:

```python
class LLMClientWrapper(LLM):
    client: LLMClient
    temperature: float = 0.2

    def __init__(self, client: LLMClient, temperature: float = 0.2):
        # явно сохраняем поля в экземпляре
        self.client = client
        self.temperature = temperature
        # вызов суперкласса без передачи client как "неизвестного" kwargs
        super().__init__()
```

Полный файл (фрагмент):

```python
from typing import Optional, List, Mapping, Any
from langchain_core.language_models.llms import LLM
from llm_service.llm_client import LLMClient


class LLMClientWrapper(LLM):
    """
    Лёгкий адаптер LangChain -> ваш LLMClient.
    LangChain вызывает _call, мы делегируем в LLMClient.generate.
    """

    client: LLMClient
    temperature: float = 0.2

    def __init__(self, client: LLMClient, temperature: float = 0.2):
        # ВАЖНО: сохранить client/temperature на инстансе
        self.client = client
        self.temperature = temperature
        super().__init__()

    @property
    def _llm_type(self) -> str:
        return "custom_llm_client"

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        out = self.client.generate([prompt], temperature=self.temperature)[0]
        return out or ""

    def _identifying_params(self) -> Mapping[str, Any]:
        return {"provider": getattr(self.client, "provider", None), "temperature": self.temperature}
```

Почему это важно: документация и примеры по созданию кастомного LLM показывают, что ваш класс должен реализовать `_call` и правильно хранить внутренние поля (см. примеры создания custom LLM в LangChain). Если `self.client` не установлен корректно, LangChain может попытаться вызвать / итерировать что-то неожиданное и получить `'method' object is not iterable'`. Источники/примеры по созданию custom LLM: официальная страница примеров и community-гайды. ([langchain-doc.readthedocs.io][1])

---

# 2) Ещё одна возможная причина (менее вероятна, но полезно проверить)

В некоторых версиях LangChain/Agent API `create_react_agent` / `AgentExecutor` ожидают **строку** шаблона промпта или объект PromptTemplate в точном формате; если туда попал не тот тип (например метод или объект с методом вместо строки), вы можете получить похожую ошибку. Если после исправления адаптера LLM ошибка останется — попробуйте вместо `PromptTemplate.from_template(prompt_template)` просто передать строку шаблона (или `prompt_template.template`), т.е.:

```python
with open('prompts/agent_prompt.txt', 'r', encoding='utf-8') as f:
    prompt_text = f.read()

# 1) если create_react_agent у вас плохо совместим с PromptTemplate:
prompt = prompt_text   # plain str

# 2) или оставьте PromptTemplate, если не даёт ошибок:
# prompt = PromptTemplate.from_template(prompt_text)
```

В прошлом аналогичная ошибка возникала у других пользователей, когда в `create_react_agent` передавали неподходящий тип для `prompt` (или другой параметр). ([Stack Overflow][2])

---

# 3) Что ещё проверить (диагностика)

1. После правки `LLMClientWrapper` перезапустите `uvicorn` и отправьте тот же запрос — скорее всего проблема уйдёт.
2. Если ошибка остаётся, включите более подробное логирование (в `.env` например `LLM_LOG_LEVEL=DEBUG`) и посмотрите полный traceback в логах — там будет видно, в какой строке/модуле падает итерация. (в `uvicorn` логи появятся в консоли)
3. Можно локально быстро протестировать адаптер:

```python
from llm_service.llm_client import LLMClient
from langchain_adapter import LLMClientWrapper

c = LLMClient(provider="openrouter")
w = LLMClientWrapper(c)
print(w._call("ping"))
```

(это подтвердит, что `_call` корректно вызывает `LLMClient.generate` и не падает).

---

# 4) Почему я уверен (коротко)

* Частая причина `'method' object is not iterable'` в LangChain — некорректно реализованный wrapper/передача неверного типа в agent фабрики (см. обсуждения и issue-ы). ([GitHub][3])
* Ваш `LLMClientWrapper.__init__` не присваивает `self.client` — это явная антипаттерн и частая причина «странного» поведения при интеграции кастомных LLM в LangChain (см. примеры custom LLM). Исправление — простое и часто решает подобные ошибки. ([langchain-doc.readthedocs.io][1])

---

# 5) Если после правки проблема не уйдёт — присылай стек трэйс (log)

Если вы исправите `langchain_adapter.py`, перезапустите сервис и ошибка исчезла — отлично. Если всё ещё получаете `'(agent error) TypeError: 'method' object is not iterable'`, пришлите (копию) **полный traceback** из лога uvicorn (в подсказку можно просто вставить последние ~30 строк). С ним я смогу точно сказать, в каком месте кода LangChain пытается итерировать метод и дать точную правку.

---

Если хотите, могу подготовить патч-файл (diff) для вставки или показать, как выглядит тестовый скрипт для локальной проверки адаптера — скажите, предпочитаете `diff` или просто правку кода?

[1]: https://langchain-doc.readthedocs.io/en/latest/modules/llms/examples/custom_llm.html?utm_source=chatgpt.com "Custom LLM — LangChain 0.0.107"
[2]: https://stackoverflow.com/questions/79237941/why-am-i-not-able-to-create-the-react-agent-using-create-react-agent?utm_source=chatgpt.com "python - Why am I not able to create the react agent using ..."
[3]: https://github.com/langchain-ai/langchain/issues/17821?utm_source=chatgpt.com "'function' object is not iterable #17821 - Streaming Agent ..."
