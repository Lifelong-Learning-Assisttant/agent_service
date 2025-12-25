Отлично — делаю чёткий план без кода, как ты просил:

1. список файлов и точных изменений (какие функции/классы добавить или изменить и зачем),
2. спецификацию класса `AgentSession` (поля, методы, жизненный цикл) — можно сразу взять и реализовать.

---

# 1) Список изменений файлов (какие файлы править и какие функции/фичи добавить)

> Принцип: минимально инвазивно для demo. Я разделил на «обязательно для demo» и «рекомендовано/опционально (если хочешь более чистую реализацию)».

### A. Новые файлы

1. `agent_service/agent_session.py` — **НОВЫЙ**

   * Содержит класс `AgentSession` (спецификация ниже).
   * Причина: инкапсулировать per-session state, task, notify, cancel, save/load.

### B. Изменения в `agent_service/agent_system.py`

(модифицировать/добавить; оставить старый код читаемым, но перевести на использование `AgentSession`)

* **Добавить импорты**: `from .agent_session import AgentSession` и `import asyncio`.
* **Добавить поле**: `self.sessions: Dict[str, AgentSession]` для хранения активных сессий.
* **Добавить методы:**

  * `create_session(session_id: str) -> AgentSession` — создаёт и регистрирует новый `AgentSession`.
  * `get_session(session_id: str) -> Optional[AgentSession]` — возвращает сессию или None.
  * `remove_session(session_id: str)` — удаляет сессию и очищает ресурсы.
  * `sweep_expired_sessions()` — background task/метод, который удаляет неактивные сессии (TTL).
* **Изменить сигнатуры/поведение:**

  * `run(self, question: str, session_id: str = "default")`:

    * сделать асинхронной `async def run(...)` или добавить `run_async(...)` и оставлять sync-обёртку для backward-compat.
    * Вместо прямого `self.app.invoke(...)` — запускать `AgentSession.start(question)` или `asyncio.create_task(session.run_graph(question))`.
    * Возвращать «accepted» / сразу запускать таск (для demo) или ждать завершения в зависимости от API contract.
* **Добавить/перенести notify UI helper**:

  * `async def _notify_ui_async(self, session_id, event)` или делегировать в `AgentSession.notify_ui_async`.
  * Убедиться, что notify — fire-and-forget с коротким таймаутом и `try/except`.
* **Адаптировать узлы графа**:

  * Либо узлы остаются (planner_node, retrieve_node и т.д.), но их нужно сделать `async def` (см. ниже), либо граф-wrapper вызывает их через `await session.node(...)`.
  * При каждом ключевом шаге узла — вызывать `session.notify_ui(...)`.

### C. Изменения в `agent_service/langchain_tools.py`

(добавить async-версии инструментов)

* **Добавить асинхронные функции:**

  * `async def rag_search_async(query: str, top_k: int = 5, use_hyde: bool = False) -> str`
  * `async def rag_generate_async(...)`
  * `async def generate_exam_async(...)`
  * `async def grade_exam_async(...)`
* Причина: инструменты делают HTTP-запросы; в асинхронном агенте желательно вызывать `httpx.AsyncClient` и `await`.
* **Оставить** синхронные функции для обратной совместимости, но использовать в агенте async-версии.
* **Обновить** `make_tools()` либо добавить `make_async_tools()` (опционально) if LangChain tool interface expects sync.

### D. Изменения в `agent_service/llm_service/llm_client.py` (рекомендуется)

(опционально / рекомендовано для полного async)

* **Добавить async-методы:**

  * `async def generate_async(self, texts: Sequence[str], ...) -> List[str]`
  * `async def embed_async(self, texts: Sequence[str], ...) -> List[List[float]]`
  * `async def validate_api_key_async(self, ...) -> Tuple[bool,str]`
* Причина: если агент становится полностью async, полезно иметь async интерфейсы для LLM-вызовов.
* Можно на demo реализовать «параллельную» работу через `asyncio.to_thread` для текущих sync методов (если не хочешь переписывать LangChain слои сразу).

### E. Изменения в `web_ui_service/api_endpoints.py`

(обязательное изменение для rooms и приёма progress-событий)

* **Переработать `ConnectionManager`:**

  * Ввести структуру `connections_by_session: Dict[str, Set[WebSocket]]`.
  * Методы:

    * `async def connect(websocket: WebSocket)` — принимать как раньше.
    * `async def subscribe(websocket: WebSocket, session_id: str)` — регистрирует сокет в комнате.
    * `def unsubscribe(websocket: WebSocket, session_id: str)` — удаляет.
    * `async def disconnect(websocket: WebSocket)` — полная очистка (удалить из всех комнат).
    * `async def broadcast_to_session(session_id: str, message: str or dict)`.
* **Изменить `/ws` endpoint**:

  * На соединении ожидать JSON-команду от клиента (например `{"cmd":"subscribe","session_id":"..."}`) и регистрировать подписку.
  * Поддерживать unsubscribe и корректное удаление при disconnect.
* **Добавить HTTP endpoint**:

  * `POST /api/agent/progress` — принимает progress-event JSON (см. schema в архитектуре).

    * Действия: валидация → добавить в `messages_by_session[session_id]` (deque) → `await manager.broadcast_to_session(session_id, event_json)` → return OK.
* **Заменить `messages_list` на `messages_by_session: Dict[str, Deque]`** и добавить `GET /api/messages?session_id=...` для получения истории.
* **Добавить опциональную проверку internal token**: читать `X-INTERNAL-TOKEN` из env (для безопасности).

### F. Изменения в `web_ui_service/web_ui.py`

(адаптировать UI для работы с room-based WS и историей)

* **Добавить клиентскую часть (JS) в NiceGUI-страницу**:

  * При открытии страницы: открыть WebSocket `/ws`, при соединении шлёшь `{"cmd":"subscribe","session_id": "<текущий session_id>"}`.
  * При получении сообщений WS — добавлять их в UI через `add_message("AgentProgress", ...)`.
* **Изменить логику загрузки истории**:

  * При старте страницы делать `GET /api/messages?session_id=...` и отрисовывать историю (messages_by_session).
* **UI**: в `show_messages()` отделять обычные Agent/User сообщения и progress-события (`AgentProgress`) и отображать в другом стиле (строгое форматирование/серые строки).
* **Добавить контрол для выбора/ввода `session_id`** (или получать session_id из серверного состояния) — для демо нужно управлять двумя пользователями.

### G. Дополнительно (опционально, но полезно)

1. `agent_service/settings.py` — добавить новую конфигурацию `web_ui_internal_token` (если используешь проверку) и `session_ttl_seconds` для sweeper.
2. `agent_service/README.md` (или docs) — краткая инструкция, как включить progress-notify и тестировать with two browsers.
3. `web_ui_service/pyproject.toml` / `agent_service/pyproject.toml` — если добавляешь `async` зависимости (`httpx>=0.23` уже есть), проверить совместимость.

---

# 2) Спецификация класса `AgentSession` (поля, методы, lifecycle) — **без кода**, готово для быстрой реализации

> Цель: чёткая, минимальная и прагматичная реализация для demo, покрывающая все нужды (state, task, notify, cancel, persistence hook).

## Название

`AgentSession` (в файле `agent_service/agent_session.py`)

---

## Основные свойства / поля (state)

1. **session_id: str**
   Идентификатор сессии (уникально).

2. **state: AgentState**
   Текущий объект состояния агента (тот же `AgentState` TypedDict или аналог), хранит `question`, `intent`, `documents`, `quiz_content`, `user_solution`, `final_answer` и т.д.

3. **task: Optional[asyncio.Task]**
   Текущая асинхронная задача, выполняющая граф/раннер; `None` если ничего не выполняется.

4. **last_active_at: datetime**
   Метка времени последней активности (вход пользователя или обновление прогресса); используется для TTL/eviction.

5. **created_at: datetime**
   Время создания сессии.

6. **last_events: Deque[dict]** (например `collections.deque(maxlen=200)`)
   Набор последних progress-событий для этой сессии (история). Служит для отдачи истории при переподключении клиента.

7. **lock: asyncio.Lock**
   Асинхронный лок для корутин, которые меняют state (предотвращает race conditions).

8. **cancelled: bool**
   Индикатор отмены (если пользователь нажал stop).

9. **config / opts: dict** (опционально)
   Пер-Session параметры (например `temperature`, `provider`), если нужно.

10. **reference to parent AgentSystem** (weakref или прямой ref)
    Чтобы `AgentSession` мог вызывать `notify_ui` (через агент) или сохранять state.

---

## Основные методы (интерфейс)

### Инициализация / создание

* `__init__(session_id: str, agent_ref, initial_state: Optional[AgentState] = None, **opts)`

  * Создаёт объект, инициализирует поля, `last_events` deque и `lock`.

### Запуск / обработка вопроса

* `async def start(question: str) -> None`

  * Основной вход: принимает вопрос, обновляет state.question, обновляет `last_active_at`, запускает `self.task = asyncio.create_task(self._run_graph(question))` (или синхронный fallback).
  * Должен вернуть быстро (не блокируя вызывающий поток), для demo можно return immediately or await result depending on API contract.

* `async def _run_graph(question: str) -> None`  *(внутренний)*

  * Собственно выполнение последовательности узлов (planner, retrieve, create_quiz, evaluate).
  * На каждом ключевом шаге вызывает `await self.notify_ui(event)` (см. ниже).
  * При завершении записывает final_answer в `state` и добавляет финальное событие.
  * Ловит исключения и публикует `tool_error` в UI.

### Прогресс / уведомления

* `async def notify_ui(self, step: str, message: str, tool: Optional[str] = None, level: str = "info", meta: Optional[dict] = None) -> None`

  * Формирует стандартный event (см. event schema) и:

    1. Добавляет event в `self.last_events` (deque).
    2. Вызывает parent-agent или напрямую делает HTTP POST к `web_ui` (`/api/agent/progress`) с коротким timeout (fire-and-forget).
    3. Не должен бросать исключения (все ошибки логируются).
  * Для demo — `notify_ui` может использовать sync `httpx.post` в `asyncio.to_thread` или `httpx.AsyncClient` `await` (предпочтительно).

### Взаимодействие с инструментами

* `async def call_tool(self, tool_name: str, *args, **kwargs) -> Any`

  * Унифицированный обёртка для вызова инструментов (rag_search_async, generate_exam_async и пр.).
  * Перед вызовом отправляет `start_tool` событие, при прогрессе — `progress` события (если инструмент это предоставляет), после — `tool_done` или `tool_error`.

### Отмена / стоп

* `async def cancel(self) -> None`

  * Устанавливает `cancelled = True`, отменяет `self.task` (если есть) через `self.task.cancel()` и вызывает cleanup.
  * Посылает `notify_ui(step="cancelled", message="Пользователь отменил выполнение")`.

### Сохранение/восстановление (hooks)

* `async def save_state(self) -> None`

  * Hook для сериализации `self.state`/`last_events` в персистентное хранилище (Redis/DB). Для demo — можно no-op или sync save to file.

* `async def load_state(self) -> None`

  * Hook для восстановления (опционально).

### Утилиты

* `def is_running(self) -> bool`

  * Возвращает `True` если `self.task` и не `done()`.

* `def touch(self) -> None`

  * Обновляет `last_active_at = now()`; вызывать при входе от пользователя.

* `async def cleanup(self) -> None`

  * Освобождает ресурсы, удаляет ссылки, отменяет таск если нужно и очищает хвост событий. Вызывается `AgentSystem.remove_session()`.

---

## Жизненный цикл `AgentSession` (lifecycle)

1. **Создание:** `AgentSystem.create_session(session_id)` — создает объект, ставит в `self.sessions`.
2. **Инициализация:** `session.load_state()` (если есть сохранение).
3. **Запуск:** пользователь посылает запрос → `session.start(question)` → начинает выполняться `session._run_graph(...)` в background task.
4. **Во время выполнения:**

   * `session.notify_ui(...)` отправляет прогресс;
   * `session.call_tool(...)` вызывает async-инструменты;
   * `session.touch()` обновляет `last_active_at`.
5. **Завершение:**

   * При успешном завершении `state.final_answer` выставляется, `notify_ui(step="final_answer", ...)` рассылает финальный результат.
   * `session.task` завершён; `is_running()` → False.
6. **Продолжение/повтор:** пользователь может послать новый `start(...)` — либо разрешить последовательные задачи, либо вернуть «session busy» в API (по выбору).
7. **Отмена:** `session.cancel()` прерывает работу и отправляет уведомление cancel.
8. **Eviction / GC:** background sweeper в `AgentSystem` вызывает `session.cleanup()` и `remove_session(session_id)` если `now - last_active_at > TTL`.

---

## Дополнительные рекомендации по реализации `AgentSession` (быстрое руководство)

* Используй `asyncio.Lock` для защиты `state` от конкурентных модификаций.
* В `notify_ui` формируй `event_id` (UUID) и включай ts (UTC ISO). Это облегчит idempotency и отладку.
* `last_events` — deque с ограничением размера (например 200) — чтобы UI мог при подключении запросить историю.
* При создании таска используй `asyncio.create_task(self._run_graph(...))` и сразу сохраняй `self.task`.
* При cancel: аккуратно обработать `asyncio.CancelledError` в `_run_graph` и отправить `tool_error`/`cancelled` в UI.
* Для demo TTL sweeper можно запускать каждые N секунд (например 30s) и удалять сессии без активности > 30min (или 10min для теста).
