# Краткое резюме

# P0 — критично исправить до продакшена

### 1) Несоответствие типов и явная ошибка: `rag_search` → `retrieve_node` → `rag_answer_node`

* **Что происходит сейчас:**
  `langchain_tools.rag_search` возвращает `json.dumps(result, ...)` — т.е. строку JSON.
  В `agent_system.retrieve_node` пишется `docs = rag_search(q)` и `documents` сохраняется как `docs` (строка).
  В `rag_answer_node` потом делается `context = "\n".join(state.get("documents", []))`. Но если `documents` — строка, `"\n".join(...)` пройдёт по символам строки и соберёт их через `\n` — **абсолютно неверный результат**.
* **Последствия:** полностью битая RAG-ветка — результаты не будут корректно подмешаны к prompt'у.
* **Как быстро исправить:**
  — `rag_search` должен возвращать `List[str]` или `List[Dict]`, а не сериализованный JSON-строкой.
  — либо в `retrieve_node` парсить JSON и привести к ожидаемому формату списка:

```python
# langchain_tools.py
def rag_search(...)-> List[str]:
    ...
    result = _post_json(...)
    # ожидаем {'documents': [...]} или list
    if isinstance(result, dict) and "documents" in result:
        docs = result["documents"]
    elif isinstance(result, list):
        docs = result
    else:
        docs = [str(result)]
    return docs
```

— и убрать `json.dumps` из `rag_search` (он мешает).

### 2) `LLMClient.generate()` делает `validate_api_key()` на каждый вызов

* **Проблема:** `generate()` и `embed()` перед каждым батчем вызывают `validate_api_key()`, который делает реальный LLM-вызов `ping`. Это добавляет лишнюю латентность и расход токенов/денег и может привести к превышению rate limits.
* **Решение:** кешировать результат проверки ключа (TTL, например 5–15 минут) или выполнять проверку один раз при старте сервиса.
  Пример:

```python
# LLMClient.__init__
self._api_key_status = None
self._api_key_checked_at = 0.0

# в generate()
if not self._is_api_key_ok_cached():
    ok, reason = self.validate_api_key()
    cache the result...
```

### 3) docker-compose командная строка — выглядит сломанной / нестандартной

`docker-compose` использовать `command: ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8250"]`.

### 4) Инициализация `AgentSystem()` — тяжёлая и выполняется при импорте FastAPI

* **Что:** `app.py` делает `agent = AgentSystem()` при импорте модуля. Это конструирование клиента LLM (возможно проверка ключей, создание сетевых клиентов) происходит синхронно при старте процесса.
* **Риск:** замедленный старт сервиса и возможный провал старта, если внешние переменные/ключи отсутствуют.
* **Решение:** ленивый init: создавать агент при первом запросе или в event startup FastAPI handler (и логически обрабатывать отсутствие ключей).

Пример:

```python
agent = None

@app.on_event("startup")
def startup():
    global agent
    agent = AgentSystem()
```

### 5) Router LLM классификатор — очень хрупкий

* **Проблема:** `_determine_intent` / `router` полагаются на свободный текст от LLM, затем делают `intent = self.client.generate(...)[0].strip().lower()` и верят этому. LLM может ответить словом с описанием, с пунктом, с лишними символами → всё может сломаться.
* **Решение:** явно попросить LLM вернуть *точную строку* из набора допустимых значений и валидировать; при невалидном результате — fallback на rule-based. Пример prompt:
  `"Ответь ОДНОЙ из: general, rag_answer, generate_quiz, evaluate_quiz. Никаких других слов."`
  Потом `if result not in set(...): -> default`.

---

# P1 — срочные и важные улучшения

### 8) `settings.get_settings()` создаёт новый экземпляр каждый вызов

* В коде много мест вызывают `get_settings()` — каждый вызов создаёт `LLMSettings()` и парсит `app_settings.json` и `.env`. Частые создания — небольшая потеря производительности и несогласованность, если что-то динамически меняется.
* **Рекомендуется:** использовать синглтон (создать объект при старте и переиспользовать) или сделать `get_settings()` кеширующим. Это упростит логирование и отладку.

### 9) `langchain_tools` — ошибки в обработке таймаутов и возвращаемых типов

* `_post_json`/`_get_json` используют `httpx.Client(timeout=timeout)` — в разных местах `timeout` передаётся как `settings.http_timeout_s` (float) — это допустимо, но лучше унифицировать и пользоваться `build_httpx_timeout(...)` из `llm_service.utils` для явности.
* Некоторые функции (например `rag_generate`, `generate_exam`) возвращают `json.dumps(result, ensure_ascii=False)` — в коде выше лучше возвращать структуру данных (`dict`) и преобразовывать в JSON только при необходимости (API层).

# P2 — рекомендации по коду, безопасность, производительность

### 11) Логи — формат и дублирование

* `get_logger` устанавливает `propagate=False`. Это нормально, но нужно убедиться, что при многократных вызовах не создаются дублирующие хендлеры — сейчас код проверяет `if not log.handlers` — ok. Рекомендую единообразно использовать `get_logger` везде (сейчас это так).

### 12) Обработка exceptions — трассировка и пользовательские ошибки

* В `app.py` исключения возвращаются 500 с `str(e)`. Лучше логировать стектрейс и возвращать краткую дружелюбную ошибку пользователю, а полную информацию — в логах/trace.

# Конкретные баги и «странности» (буквально — что выглядит нелогичным)

1. **`rag_search` возвращает JSON-строку, но код ожидает список документов.** (см. P0)
4. **`langchain_agent.py`/`langchain_adapter.py` — экспериментальные адаптеры, не используемые в сервисе.** Лучше переместить/удалить.
5. **`LLMClient.generate()` вызывает `validate_api_key()` каждый раз.** (см. P0)
6. **Неконсистентное использование timeouts:** `llm_service.utils.build_httpx_timeout(...)` есть, но `langchain_tools` не использует его везде.
7. **`pyproject.toml` зависимости общие и широкие — риск несовместимости LangChain API.**
10. **`settings.LLMSettings.__init__` логика применения `app_settings.json` выглядит странно:** она переписывает только те значения, где текущее значение равно полю default — это может вести к неожиданному поведению при явных override’ах. (если в будущем захочешь, прокомментирую подробно).

# Быстрые правки/патчи (copy-paste готовые фрагменты)

### Исправление `rag_search` (с возвращением списка)

```python
# langchain_tools.py
def rag_search(query: str, top_k: int = 5, use_hyde: bool = False) -> List[str]:
    rag_service_url = settings.rag_service_url
    if not rag_service_url:
        log.warning("RAG service not configured")
        return []
    try:
        payload = {"query": query, "top_k": top_k, "use_hyde": use_hyde}
        result = _post_json(f"{rag_service_url}/search", payload, settings.http_timeout_s)
        # result может быть dict с ключом 'documents' или список
        if isinstance(result, dict) and "documents" in result:
            docs = result["documents"] or []
        elif isinstance(result, list):
            docs = result
        else:
            docs = [str(result)]
        # привести все элементы к строкам
        return [str(d) for d in docs]
    except Exception as e:
        log.error("RAG search failed: %s", e)
        return []
```

### В `agent_system.retrieve_node` — ожидание списка

```python
def retrieve_node(self, state):
    q = (state.get("question") or "").strip()
    docs = rag_search(q)
    if isinstance(docs, str):
        try:
            docs = json.loads(docs)
        except Exception:
            docs = [docs]
    # убедимся, что это список строк
    if isinstance(docs, dict):
        docs = docs.get("documents", [])
    docs = [str(d) for d in (docs or [])]
    return {**state, "documents": docs}
```

### Кеширование `validate_api_key`

(простейший вариант)

```python
import time

class LLMClient:
    def __init__(...):
        ...
        self._api_key_ok = None
        self._api_key_ok_ts = 0.0
        self._api_key_ttl = 60 * 10  # 10 минут

    def _is_api_key_ok_cached(self):
        return self._api_key_ok and (time.time() - self._api_key_ok_ts < self._api_key_ttl)

    def generate(...):
        if not self._is_api_key_ok_cached():
            ok, reason = self.validate_api_key()
            self._api_key_ok = ok
            self._api_key_ok_ts = time.time()
            if not ok:
                self.log.warning("API key validation failed: %s", reason)
                return ["" for _ in texts]
        ...
```

# Итог: приоритетный план действий (предложение)

1. (P0) Исправить `rag_search`/`retrieve_node` типы и любую логику join'а. (Быстрое исправление — 15–30 минут)
2. (P0) Убрать/кешировать `validate_api_key()` вызовы в `LLMClient`. (30–60 минут)
4. (P0) Сделать ленивую инициализацию агента в `app.py` (или инициализацию в startup event). (10–20 минут)
5. (P1) Перенести/удалить устаревшие файлы: `agent/`, `langchain_adapter.py`, `langchain_agent.py`. (10–15 минут)
6. (P1) Проверить и зафиксировать зависимости в `pyproject.toml` + добавить CI с unit tests. (чуть дольше)
7. (P2) Улучшение логирования, timeouts на уровне graph/invoke, test coverage, security (env handling). (опционально/по очереди)
