# 1. Краткая сводка (высокоуровнево)

* Проект в целом устроен логично: есть слой настроек, LLM-клиент, адаптер для LangChain, инструменты, FastAPI-оболочка и отдельный простой агент (langgraph).
* **Критические (runtime) ошибки** связаны с несоответствием имён полей настроек (`settings`) и использованием этих полей в `langchain_tools.py`. Это приведёт к `AttributeError` при запуске.
* Есть риски несовместимости API LangChain (функции/методы, которые зависит от версии `langchain` / `langchain-core`)
* Рекомендую ряд улучшений архитектуры (сегрегация настроек LLM vs. сервисов, кэширование клиентов, обработка ошибок старта).

---

# 2. Критические проблемы (надо исправить в первую очередь)

## A. Несоответствие полей `settings` → **langchain_tools.py** (очень критично)

**Проблема:** В `langchain_tools.py` используются атрибуты `settings.CONTEXT7_URL`, `settings.TAVILY_URL`, `settings.HTTP_TIMEOUT_S`, а в `settings.py` таких полей нет — там другие имена (`request_timeout_s`, `connect_timeout_s`, …).
**Последствие:** при импорте модуля или при вызове функций будет `AttributeError: 'LLMSettings' object has no attribute 'CONTEXT7_URL'`.

**Исправления (варианты):**

1. **Лучше:** расширить модель настроек, добавив поля для внешних сервисов (context7, tavily и глобальный http timeout).
2. **Быстрее:** поменять обращения в `langchain_tools.py` на существующие имена (`request_timeout_s`) и безопасно читать URL через `getattr(settings, "context7_url", None)`.

**Рекомендуемый патч (предпочтую 1 — расширить настройки).**
Добавьте в `settings.py` новые поля (в `LLMSettings`) — пример:

```python
# В settings.py, в класс LLMSettings (пример упрощённо)
    # ---- External services (URLs and timeouts) ----
    context7_url: str | None = Field(default=None, env="CONTEXT7_URL")
    tavily_url: str | None = Field(default=None, env="TAVILY_URL")
    http_timeout_s: float = Field(default=60.0, env="HTTP_TIMEOUT_S")
```

И в `langchain_tools.py` заменить обращения:

```python
# прежнее
if not settings.CONTEXT7_URL:
# новое
if not getattr(settings, "context7_url", None):
```

и таймаут передавать как `timeout=settings.http_timeout_s` (или лучше использовать httpx.Timeout).

---

## C. Непроверяемые/версионозависимые вызовы LangChain API

**Проблемы/места риска:**

* `create_agent(self.llm, self.tools, prompt)` — сигнатура `create_agent` может отличаться в разных версиях LangChain / langchain-core.
* `LLMClientWrapper` вызывает `super().__init__(client=client, temperature=temperature)` — это может не соответствовать сигнатуре базового `LLM` (зависит от версии).
* В `LangchainAgentService.run` используется `self.agent.invoke(prompt)` — AgentExecutor/agent API может иметь `run()` / `__call__` / `invoke` и т.д.

**Рекомендации:**

* Зафиксировать версии LangChain в `pyproject.toml` (точнее) и проверить локально (pip show langchain), либо адаптировать код с учётом нескольких возможных сигнатур (try/except с поддерживаемыми вариантами).
* Заточить код под эту версию.

# 3. Мажорные проблемы / архитектурные замечания

## 3.1. Смешение конфигураций LLM и сервисов в одном `LLMSettings`

* Сейчас `LLMSettings` содержит только LLM-поля, но код ожидает и сервисные URL (tavily/context7). Рекомендую создать **две** Pydantic Settings-классы:

  * `LLMSettings` (LLM_* env prefix)
  * `AppSettings` / `ServiceSettings` (без префикса, или с другим префиксом `APP_`), куда положить `TAVILY_URL`, `CONTEXT7_URL`, `HTTP_TIMEOUT_S` и т.п.
* Это улучшит читаемость, env-конфигурацию и отделит секреты от общих настроек.

## 3.2. Создание тяжелых объектов при каждом запросе

* `LLMClient.generate` каждый раз создаёт `chat = self.create_chat(...)`. Это нормально, но может быть дорого. Рассмотрите кэширование/реюз chat-клиента внутри `LLMClient` (по provider+model+api_key), с безопасностью потоков (thread-safe) и TTL.
* В `app.py` вы уже создаёте `AGENT_SERVICE` один раз — хорошо. Но если пользователь укажет `provider` отличающийся от дефолтного — код создаёт новый `LangchainAgentService` **на каждом запросе**, что может быть тяжело. Лучше иметь фабрику/кэш агентов по provider.

## 3.3. Логгирование секретов

* Вы используете `SecretStr` — хорошо. Убедитесь, что нигде не делаете `str(secret)` или `.get_secret_value()` в логах. В `settings.__main__` вы печатаете булевы значения — ок; но не выводить сами ключи.

## 3.4. Обработка ошибок старта приложения

* Сейчас `AGENT_SERVICE` создаётся на импорт времени. Если при init агент падает — приложение не поднимется. Предпочтительна отложенная инициализация (lazy), либо явная обработка ошибок с fallback (например, режим read-only).

---

# 4. Мелкие, но полезные улучшения и замечания

* `logger.get_logger` использует `get_settings()` — при старте логгера это загрузит настройки; это нормально, но учтите, что get_settings создаёт объект pydantic при каждом вызове (в коде это так задумано). При больших системах можно сделать singleton settings.
* В `llm_client._call_with_retry` параметры `max_tries` и `sleep_seconds` хардкодятся; можно брать из `settings.max_retries` и `settings.retry_base_s`.
* В `llm_service/create_chat` для OpenRouter вы строите `headers = openrouter_headers(...)` и передаёте в ChatOpenAI как `default_headers=headers` — проверьте, что версия `langchain-openai` принимает `default_headers` и `base_url`. (версионный риск).
* В `langchain_tools._post_json` лучше использовать `httpx.Timeout(...)` вместо числового timeout, и передавать `client.post(..., timeout=timeout)` — сейчас вы передаёте `Client(timeout=timeout)`; это нормально, но предсказуемее явно.
* `pyproject.toml` указывает `requires-python = ">=3.13"` — очень новая версия, убедитесь, что CI/окружение её поддерживает (много окружений пока 3.11/3.12). Если цель — широкая совместимость, понизьте до `>=3.11`.

---

# 5. Конкретные правки — патч-список (копировать/вставить)

## 5.1. Добавить поля в `settings.py`

Вставьте эти поля в `LLMSettings` (пример):

```python
    # ---- External MCPs & App-level settings ----
    # (URLs можно задавать через переменные окружения CONTEXT7_URL, TAVILY_URL)
    context7_url: str | None = Field(default=None, env="CONTEXT7_URL")
    tavily_url: str | None = Field(default=None, env="TAVILY_URL")
    http_timeout_s: float = Field(default=60.0, env="HTTP_TIMEOUT_S")
```

(Опционально: создайте отдельный `AppSettings` класс, если хотите разделение.)

## 5.2. Исправить `langchain_tools.py` на использование новых полей и безопасные getattr:

Пример замены (фрагменты):

```python
def context7_sync(query: str) -> str:
    url = getattr(settings, "context7_url", None)
    if not url:
        log.warning("Context7 not configured; returning mock")
        return f"(Context7 mock) {query[:300]}"
    try:
        data = _post_json(str(url), {"q": query}, timeout=getattr(settings, "http_timeout_s", 60.0))
        ...
```

и аналогично для `tavily_sync` (использовать `tavily_url`).

# 8. Быстрый приоритетный чек-лист (что сделать прямо сейчас)

1. Исправить `langchain_tools.py` → использовать `settings.context7_url`, `settings.tavily_url`, `settings.http_timeout_s` или добавить поля в `settings.py`. (Критично)
