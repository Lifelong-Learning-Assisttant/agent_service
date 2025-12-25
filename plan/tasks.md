# Порядок работ и общая последовательность (минимально-зависимая)

1. Подготовка окружения (локальные mocks + CI) — Task A
2. Инфраструктурные правки Web UI: rooms WS + /api/agent/progress + messages_by_session — Task B
3. AgentSession (каркас) + sessions map в AgentSystem — Task C
4. Асинхронные инструменты (langchain_tools async) — Task D
5. Перевод AgentSystem на использование AgentSession и async run — Task E
6. Notify UI (async) интеграция в узлы — Task F
7. Клиентская часть Web UI: подписка по session_id и отрисовка progress — Task G
8. Тесты: unit, integration и e2e — Tasks H1..H3
9. Документация, CI, чек-лист PR/релиза — Task I

Важный принцип: сначала делаем минимальную работоспособную цепочку «agent → POST /api/agent/progress → web_ui.broadcast room», затем эволюционируем agent в полностью async и per-session.

# Задача A — Подготовка окружения и mock-сервисов

Цель: подготовить локальное dev-окружение для интеграционного тестирования (mock RAG, mock TestGenerator), обновить docker-compose-dev (или сценарии запуска) и CI для запуска тестов.

Действия / файлы:

Добавить простые mock-сервисы:

mocks/rag_mock.py (FastAPI) — /search и /rag возвращают фиктивные чанки.

mocks/test_generator_mock.py — /api/generate, /api/grade.

Создать новый docker-compose-dev-mock.yml (корневой или в agent_service/) чтобы поднимать agent, web_ui, и два mock-сервиса для локального теста.

Добавить tests/fixtures/ с конфигурациями для тестов (адреса mock-сервисов).

Подзадачи:

Write README dev-run steps: docker compose -f docker-compose-dev_mock.yml up --build.

Add environment variables example .env_example.

Acceptance criteria:

docker-compose-dev поднимает agent, web_ui и mocks, и все health endpoints возвращают 200.

CI может поднять контейнеры в job (или тесты используют pytest + httpx mocking).

Сложность: низкая
Кому: DevOps / mid backend


# Задача B — Web UI: подписки по session (rooms) + progress endpoint

**Цель:** заменить одно глобальное `messages_list` на комнатную модель, предоставить `/api/agent/progress` и WS subscribe/rooms.

**Действия / файлы:**

* `web_ui_service/api_endpoints.py`:

  * Реализовать `connections_by_session: Dict[str, Set[WebSocket]]`.
  * Добавить методы: `subscribe(ws, session_id)`, `unsubscribe`, `broadcast_to_session(session_id, event)` и `disconnect` очистку.
  * Изменить `/ws` handler: при подключении ожидать JSON команды `{"cmd":"subscribe","session_id":"..."}` и регистрировать в комнате. Обрабатывать unsubscribe и disconnect.
  * Добавить `POST /api/agent/progress` — принимает event JSON, валидирует, кладёт в `messages_by_session[session_id]` (collections.deque(maxlen=N)) и вызывает `await manager.broadcast_to_session(...)`.
  * Добавить `GET /api/messages?session_id=...` — вернуть историю `messages_by_session[session_id]`.
  * (Опционально) Проверка заголовка `X-INTERNAL-TOKEN` для internal calls.

**Подзадачи:**

* Вынести тип event schema (pydantic `ProgressEvent`) для валидации.
* Обновить CORS и middleware по необходимости.

**Acceptance criteria:**

* WS-клиент может подписаться и получать сообщения, которые публикует `/api/agent/progress`.
* `GET /api/messages?session_id=...` возвращает историю для указанной комнаты.
* Unit-tests: manager.subscribe/ unsubscribe/ broadcast работают корректно (мок WebSocket).

**Сложность:** средняя
**Кому:** backend (web_ui) developer

---

# Задача C — Добавить `AgentSession` (каркас) и sessions map

**Цель:** создать отдельный модуль с классом `AgentSession` (каркас по спецификации) и механизмом хранения сессий в `AgentSystem`.

**Действия / файлы:**

* Создать `agent_service/agent_session.py` с классом `AgentSession` (поля и методы по спецификации, но можно сначала реализовать skeleton: поля, stubs методов, event queue, last_events deque, lock).
* В `agent_service/agent_system.py`:

  * Добавить `self.sessions: Dict[str, AgentSession]`.
  * Добавить методы `create_session`, `get_session`, `remove_session`, `sweep_expired_sessions` (sweeper запускается background).
  * В `run()` — вместо прямого invoke, получать/создавать `AgentSession` и запускать `session.start(question)` (в background task).
  * Добавить Semaphore для ограничения параллелизма.
* Добавить config `session_ttl_seconds` в settings (или использовать хардкод для demo).

**Подзадачи:**

* Добавить логирование создания/удаления сессий.
* Добавить unit-tests: create_session, start task stored, is_running etc (моки для notify_ui).

**Acceptance criteria:**

* `AgentSession` объект может создаваться, храниться, и имеет API `start`, `cancel`, `notify_ui` (stubs).
* `AgentSystem.run()` создаёт сессию и запускает фоновой таск (тест через asyncio to run background until short sleep and assert task exists).
* Sweeper удаляет сессии неактивные больше TTL.

**Сложность:** средняя
**Кому:** backend (agent) developer

---

# Задача D — Асинхронные версии инструментов (langchain_tools)

**Цель:** сделать async-обёртки для всех внешних инструментов (rag_search_async, generate_exam_async, grade_exam_async) или хотя бы подготовить интерфейс, который ожидает асинхронные вызовы.

**Действия / файлы:**

* `agent_service/langchain_tools.py`:

  * Реализовать async-функции с `httpx.AsyncClient` для `/search`, `/rag`, `/api/generate`, `/api/grade`.
  * Сохранить существующие sync версии (для обратной совместимости).
  * Log/timeout handling and exceptions.
* Добавить тесты для async-functions: использовать pytest-asyncio and respx/httpx mocking to emulate remote responses.

**Acceptance criteria:**

* `rag_search_async` делает `await` на mock endpoint и возвращает корректную JSON/str.
* Unit-tests покрывают success and error paths (timeouts, 500).

**Сложность:** средняя
**Кому:** backend developer (familiar with async + httpx)

---

# Задача E — Перевод AgentSystem на async flow и использование AgentSession

**Цель:** модифицировать `agent_system.py` чтобы узлы (planner, retrieve, etc.) корректно использовали `AgentSession` и async инструменты.

**Действия / файлы:**

* В `agent_system.py`:

  * Сделать ключевые узлы асинхронными `async def planner_node(self, session, state)` и т.д., или сохранить сигнатуры и вызывать `await asyncio.to_thread` при вызовах sync.
  * Внутри `_run_graph` или `_run_task` (в `AgentSession`) вызывать узлы шаг за шагом, держа `await session.notify_ui(...)` между шагами.
  * При вызове rag -> использовать `await rag_search_async(...)`.
  * Обрабатывать исключения: при ошибке инструмента — `session.notify_ui(step='tool_error', ...)` и корректный rollback/cleanup.
* Обновить `run()` API: для demo вернуть immediate acknowledgement and spawn background task; создать опциональную sync wrapper for backward compatibility.

**Подзадачи:**

* Добавить логирование timing per-step.
* Добавить unit-tests: mock rag/tool calls and assert notify_ui called with expected events (use monkeypatch or respx).

**Acceptance criteria:**

* При `AgentSession.start()` tasks выполняются асинхронно, `AgentSystem` не блокируется.
* В тестах simulate ask "generate quiz": verify sequence notify_ui calls: intent_determined → start_retrieval → retrieval_done → start_generate_exam → generate_done → final_answer.

**Сложность:** высокая
**Кому:** senior backend (async experience)

---

# Задача F — notify_ui (async) и интеграция в узлы

**Цель:** реализовать надежную non-blocking отправку progress-событий в web_ui (через `/api/agent/progress`).

**Действия / файлы:**

* `agent_service/agent_session.py` (или AgentSystem helper):

  * Реализовать `async def notify_ui(event: ProgressEvent)`:

    * Формирует event JSON (event_id uuid, ts ISO, session_id, step, tool, meta).
    * Пытается `await httpx.AsyncClient.post(web_ui_url, json=event, timeout=1.0)`.
    * Обработка ошибок: retry 1 time for network error, else log and append event to local `last_events` (for history).
    * Ensure notify never raises.
* В ключевых узлах (planner, retrieve, create_quiz, evaluate) вызывать `await session.notify_ui(...)` перед/после инструментов.

**Acceptance criteria:**

* `notify_ui` делает попытку отправки и возвращает быстро. Tests mock httpx to simulate success/failure and assert function handles both.
* Integration test: run session, assert web_ui mock received progress POSTs.

**Сложность:** средняя
**Кому:** backend developer

---

# Задача G — Клиентская часть Web UI: subscribe и отрисовка progress

**Цель:** сделать фронтенд (NiceGUI) способным подписываться на WS room и отображать progress события.

**Действия / файлы:**

* `web_ui_service/web_ui.py`:

  * При инициализации страницы либо получить `session_id` из сервера/поля, либо добавить input для вводa session.
  * Открыть WS `/ws`, и после открытия отправить `{"cmd": "subscribe", "session_id": "..."}`
  * Обрабатывать входящие сообщения JSON: если event.level == error -> визуально выделять.
  * При reconnect — сделать `GET /api/messages?session_id=...` для восстановленной истории.
* Обновить `show_messages()` to render progress events separately (different style).

**Acceptance criteria:**

* В браузере при подписке видно live progress events coming from agent.
* Client recovers history after refresh by calling `GET /api/messages?session_id=...`.

**Сложность:** средняя
**Кому:** frontend / fullstack (NiceGUI)

---

# Задача H1 — Unit tests (модульные)

**Цель:** покрыть логические блоки unit-тестами.

**Требуемые тесты:**

* `agent_session` unit tests:

  * создание, touch, last_events append, is_running status.
  * notify_ui stubbed — ensure no exceptions.
* `langchain_tools` async functions:

  * success, timeout, 500 error (use respx/httpx mocking).
* `web_ui_service/api_endpoints.py` manager:

  * subscribe/unsubscribe/broadcast functions (mock websockets).
* `agent_system` helper methods:

  * create_session/get_session/remove_session, sweeper.

**Acceptance criteria:**

* pytest suite runs locally and passes.
* Coverage target: unit-level critical components >= (project standard, e.g. 70%).

**Сложность:** средняя
**Кому:** developer with pytest experience

---

# Задача H2 — Integration tests

**Цель:** интеграционное тестирование: agent → progress → web_ui (mocked or running).

**Требуемые тесты:**

* Start docker-compose-dev with mocks; run real agent and web_ui; simulate HTTP POST from browser to agent.run and assert web_ui mock or real WS received sequence of progress posts.
* Test multi-session isolation: start session A and B concurrently, ensure events of A not delivered to clients subscribed to B.

**Acceptance criteria:**

* Integration tests verify full flow end-to-end in CI job (or local script).
* Failures provide logs and traces.

**Сложность:** высокая
**Кому:** SDET / senior dev

---

# Задача H3 — End-to-end (manual + automated) test scenarios

**E2E Scenarios (to automate with Playwright or Selenium or Cypress if needed, else manual):**

1. **Happy path:** user asks "Create quiz", UI shows sequence of progress and final quiz.
2. **RAG failure:** mock RAG return 500 → agent posts `tool_error` and final message informs failure.
3. **UI reconnect:** While agent works, refresh the browser -> ensure history loaded and live events continue.
4. **Cancel:** user cancels session during generation -> agent task cancelled, UI gets `cancelled` event.
5. **Multiple sessions:** two browsers with different session_ids get only their own events.

**Acceptance criteria:**

* E2E tests should pass in smoke pipeline or be runnable locally and produce pass/fail report.

**Сложность:** high (depends on automation infra)
**Кому:** QA / SDET

---

# Задача I — Docs, CI, PR checklist, rollout

**Цель:** обеспечить воспроизводимость и качество релизов.

**Действия:**

* Update README with new endpoints and run instructions (dev compose).
* Add CI jobs:

  * unit tests (pytest), lint, mypy (optional).
  * integration smoke job: bring up docker-compose-dev and run a basic script that posts question to agent and checks web_ui messages endpoint or WS.
* PR checklist template:

  * Tests added/updated.
  * Behavior described in PR description.
  * Manual test steps included.
  * Security: internal token used (if enabled).
* Rollout plan:

  * Deploy in staging (compose prod/dev networks), smoke tests run, then production.

**Acceptance criteria:**

* CI pipeline contains unit and integration checks; PRs must pass CI before merge.

**Сложность:** средняя
**Кому:** DevOps / team lead / SDET

---

# Дополнитель операционные рекомендации (для каждой задачи)

* **Feature branch per task**: `feature/demo-progress-<short>`
* **Atomic PRs**: один PR = одна задача (B, C, D...), маленькие и ревью-простые.
* **Reviewers**: backend lead + one peer; for frontend changes include frontend reviewer.
* **Logging & tracing**: добавить correlation_id/session_id в логи, включить DEBUG для интеграционных тестов.

---

# PR / Review checklist (универсальный)

* Код читаемый, docstrings присутствуют.
* Тесты покрывают изменения (unit + basic integration).
* Нет «silent exceptions» без логирования.
* Reuse existing settings/config; new config vars documented in `app_settings-dev.json.example`.
* Security: internal-only endpoints protected by Docker network or X-INTERNAL-TOKEN.
* Performance: notify_ui uses timeout and doesn’t block agent main flow.

---

# Примеры тест-кейсов (кратко, для вставки в таски тестирования)

1. Unit: `test_notify_ui_handles_failure`

   * Arrange: patch httpx.AsyncClient.post to raise TimeoutError.
   * Act: await session.notify_ui(...).
   * Assert: no exception raised; event appended to `last_events`.

2. Integration: `test_progress_flow`

   * Setup docker-compose-dev with rag_mock and test_generator_mock.
   * Client posts to `http://agent:8250/api/agent/run` with `session_id=quiz1`.
   * Wait short time, query `http://web_ui:8150/api/messages?session_id=quiz1` and assert sequence of steps present (intent_determined, start_retrieval, retrieval_done, start_generate_exam, generate_done, final_answer).

3. E2E: `test_two_sessions_isolation`

   * Open two WS clients subscribe `quizA` and `quizB`.
   * Start Agent run for both sessions concurrently.
   * Assert client A receives only events with session_id=quizA and B only quizB.

---

# Роли / назначение исполнителей (рекомендация)

* **Backend (Agent)** — senior or mid: Tasks C, D, E, F, H1, H2 (owner)
* **Backend (Web UI)** — mid: Task B, G (owner)
* **Frontend / NiceGUI** — mid/fullstack: Task G, H3 (owner)
* **DevOps / SDET** — Task A, H2, H3, I (owner)
* **Reviewer / Tech lead** — review PRs and approve.

---

# Итог — готовый к использованию список задач (копировать в тикет-менеджер)

(формат: `TASK-XX: <short title> — <owner> — <priority> — <complexity>`)

1. TASK-01: Setup dev mocks and docker-compose-dev — DevOps — high priority — low
2. TASK-02: Web UI: WS rooms + messages_by_session + /api/agent/progress — WebUI backend — high — medium
3. TASK-03: AgentSession skeleton + sessions map + sweeper — Agent backend — high — medium
4. TASK-04: Async langchain_tools functions — Agent backend — high — medium
5. TASK-05: Convert AgentSystem flow to spawn AgentSession tasks (async runner) — Agent backend — high — high
6. TASK-06: Implement notify_ui async helper and integrate in nodes — Agent backend — high — medium
7. TASK-07: Frontend NiceGUI: WS subscribe + history load + progress render — Frontend — high — medium
8. TASK-08: Unit tests for agent_session, tools, webui manager — QA/Dev — medium — medium
9. TASK-09: Integration tests (docker-compose) — QA/DevOps — medium — high
10. TASK-10: E2E tests + manual test scripts — QA/SDET — medium — high
11. TASK-11: Docs, CI update, PR checklist — DevOps/TechLead — medium — medium
