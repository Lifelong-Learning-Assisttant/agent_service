# Архитектура agent_service

## Обзор проекта
Agent Service — это асинхронный сервис на базе FastAPI и LangGraph, который предоставляет интеллектуального агента для работы с RAG, генерации квизов и интерактивного обучения.

## Основные компоненты

### 1. Core Agent System
**Файлы**: `agent_system.py`, `agent_session.py`, `app.py`

#### AgentSystem
- **Назначение**: Центральный менеджер сессий и графа состояний
- **Ключевые методы**:
  - `create_session(session_id)` — создает новую сессию
  - `get_session(session_id)` — получает существующую сессию
  - `run(question, session_id)` — запускает обработку вопроса
  - `sweep_expired_sessions()` — очищает старые сессии

#### AgentSession
- **Назначение**: Управление состоянием одной сессии
- **Поля**:
  - `session_id`: str — уникальный идентификатор
  - `state`: AgentState — текущее состояние
  - `task`: Optional[asyncio.Task] — выполняющаяся задача
  - `last_events`: deque(maxlen=200) — история событий
  - `last_active_at`: datetime — время последней активности
- **Методы**:
  - `start(question)` — запускает выполнение
  - `notify_ui(step, message, ...)` — отправляет уведомления
  - `cancel()` — отменяет выполнение
  - `cleanup()` — освобождает ресурсы

#### app.py (FastAPI)
- **Эндпоинты**:
  - `POST /api/agent/run` — запуск агента
  - `GET /api/messages` — получение истории сообщений
  - `GET /api/agent/progress` — получение прогресс-событий
  - `POST /api/agent/progress` — прием событий от агента (для Web UI)
  - `POST /api/session/cancel` — отмена сессии
  - `POST /api/agent/clear_session` — очистка истории
  - `POST /api/agent/end_session` — завершение сессии
  - `GET /api/agent/sessions` — список активных сессий
  - `GET /api/agent/status` — статус агента
  - `WebSocket /ws` — подписка на real-time события

### 2. LangGraph Graph
**Файл**: `agent_system.py` (метод `_build_graph`)

#### Состояние (AgentState)
```python
class AgentState(TypedDict, total=False):
    question: str
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"]
    documents: List[str]
    quiz_questions: List[Dict[str, str]]  # {"q": "...", "a": "..."}
    current_quiz_index: int
    user_answers: List[str]
    final_answer: str
```

#### Узлы графа
1. **planner** — определяет намерение пользователя
2. **retrieve** — ищет документы в RAG
3. **direct_answer** — отвечает напрямую через LLM
4. **rag_answer** — генерирует ответ на основе найденных документов
5. **create_quiz** — создает квиз и задает первый вопрос
6. **process_answer** — обрабатывает ответ пользователя и выдает следующий вопрос
7. **evaluate_quiz** — оценивает ответы и дает обратную связь

#### Поток выполнения
```
START → planner → (direct_answer | retrieve | process_answer | evaluate_quiz) → END
retrieve → (rag_answer | create_quiz)
process_answer → (END | evaluate_quiz)
```

### 3. LLM Service
**Файлы**: `llm_service/llm_client.py`, `llm_service/utils.py`

#### LLMClient
- **Поддерживаемые провайдеры**: OpenAI, OpenRouter, Mistral, Z.ai
- **Модели Z.ai**: GLM-4.7, GLM-4.6V (с поддержкой Reasoning)
- **Методы**:
  - `create_chat()` — создает чат-модель
  - `create_embeddings()` — создает модель эмбеддингов
  - `generate(texts)` — генерация ответов
  - `embed(texts)` — создание эмбеддингов
  - `validate_api_key()` — проверка ключа API

#### Утилиты
- `build_httpx_timeout()` — таймауты HTTP
- `parse_retry_after()` — парсинг заголовка Retry-After
- `unwrap_http_exc()` — извлечение деталей из HTTP исключений
- `openrouter_headers()` — заголовки для OpenRouter

### 4. Инструменты (Tools)
**Файл**: `langchain_tools.py`

#### Async инструменты
- `rag_search_async(query, top_k, use_hyde)` — поиск в RAG
- `rag_generate_async(query, top_k, temperature, use_hyde)` — генерация через RAG
- `generate_exam_async(markdown_content, config)` — генерация квиза
- `grade_exam_async(exam_id, answers)` — оценка ответов

#### Синхронные версии (для обратной совместимости)
- `rag_search()`, `rag_generate()`, `generate_exam()`, `grade_exam()`

### 5. Конфигурация
**Файлы**: `settings.py`, `app_settings-*.json`

#### LLMSettings (Pydantic)
- Загрузка из переменных окружения с префиксом `LLM_`
- Загрузка из `app_settings.json` (путь через `APP_SETTINGS_PATH`)
- Поля:
  - `default_provider`: "openai" | "openrouter" | "mistral" | "zai"
  - `openai_api_key`, `openrouter_api_key`, `mistral_api_key`, `zai_api_key` (SecretStr)
  - `web_ui_url`, `web_ui_backend_url`
  - `session_ttl_seconds`, `concurrency_limit` (дефолт: 2)
  - `test_generator_service_url`, `rag_service_url`

#### App Settings JSON
```json
{
  "web_ui_url": "http://localhost:8150",
  "session_ttl_seconds": 600,
  "concurrency_limit": 2,
  "test_generator_service_url": "http://test-generator-api:8000",
  "rag_service_url": "http://rag-api:8000"
}
```

### 6. Промпты
**Директория**: `prompts/`

- `system_prompt.txt` — системный промпт агента
- `intent_determination.txt` — промпт для определения намерения
- `reformat_latex.txt` — промпт для переформатирования формул

### 7. Сетевое взаимодействие

#### Agent → External Services
- **RAG Service**: `http://rag-api:8000`
  - `POST /search` — поиск документов
  - `POST /rag` — генерация ответа
- **Test Generator**: `http://test-generator-api:8000`
  - `POST /api/generate` — генерация квиза
  - `POST /api/grade` — оценка ответов

#### Agent → Web UI Backend
- **POST /api/agent/progress** — отправка событий прогресса
- Формат события:
```json
{
  "event_id": "uuid",
  "session_id": "uuid",
  "step": "start_planner",
  "tool": "planner",
  "message": "Анализ запроса",
  "level": "info",
  "ts": "2025-12-28T10:00:00Z",
  "meta": {"intent": "rag_answer"}
}
```

#### Docker Networks
- `web_ui_network_dev/preprod/prod` — связь с Web UI
- `rag_rag_network` — связь с RAG сервисом
- `test_generator_default` — связь с Test Generator

## Потоки выполнения

### 1. Простой вопрос (General)
```
User → AgentService
  ↓
planner → intent: "general"
  ↓
direct_answer → final_answer
  ↓
END
```

### 2. Вопрос по учебнику (RAG)
```
User → AgentService
  ↓
planner → intent: "rag_answer"
  ↓
retrieve → documents
  ↓
rag_answer → final_answer (с переформатированием LaTeX)
  ↓
END
```

### 3. Генерация квиза
```
User → AgentService
  ↓
planner → intent: "generate_quiz"
  ↓
retrieve → documents
  ↓
create_quiz → quiz_questions, first_question
  ↓
END (ожидание ответа)
```

### 4. Интерактивный квиз
```
User → AgentService (answer)
  ↓
planner → intent: "quiz_answering" (по памяти)
  ↓
process_answer → сохраняет ответ, выдает следующий вопрос
  ↓
END (ожидание следующего ответа)
```

### 5. Оценка квиза
```
User → AgentService (после последнего вопроса)
  ↓
planner → intent: "evaluate_quiz"
  ↓
evaluate_quiz → feedback, очистка state
  ↓
END
```

## Docker Compose среды

### Development (`docker-compose-dev.yml`)
- **Порт**: 8250
- **Код**: Volume mount (hot reload)
- **Конфиг**: `app_settings-dev.json`
- **Сеть**: `web_ui_network_dev`
- **Запуск**: `docker compose -f docker-compose-dev.yml up --build`

### Pre-Production (`docker-compose-preprod.yml`)
- **Порт**: 8250
- **Код**: Prod-образ (локальный)
- **Конфиг**: `app_settings-prod.json`
- **Сеть**: `web_ui_network_preprod`
- **Цель**: Тестирование перед релизом

### Production (`docker-compose-prod.yml`)
- **Порт**: 8270
- **Код**: Образ из GHCR
- **Конфиг**: `app_settings-prod.json`
- **Сеть**: `web_ui_network_prod`
- **Цель**: Production для пользователей

## Зависимости (pyproject.toml)
- `fastapi>=0.124.4` — веб-фреймворк
- `uvicorn[standard]>=0.38.0` — ASGI сервер
- `langchain==0.1.20` — фреймворк LLM
- `langchain-core==0.1.53` — ядро LangChain
- `langgraph==0.0.51` — графы состояний
- `langchain-mistralai==0.1.0` — Mistral интеграция
- `langchain-openai==0.0.8` — OpenAI интеграция
- `pydantic-settings>=2.0.0` — настройки
- `httpx` — HTTP клиент
- `pytest>=9.0.2`, `pytest-asyncio>=1.3.0` — тестирование

## Тестирование

### Unit тесты
- `tests/test_agent_session_updated.py` — 17 тестов
- `tests/test_agent_system_sessions.py` — 15 тестов

### Integration тесты
- `tests/components/test_agent_rag_integration.py`
- `tests/components/test_openrouter.py`
- `tests/components/test_rag_tools.py`
- `tests/components/test_simple_prompt.py`
- `tests/components/test_test_generator_integration.py`

### Pipeline тесты
- `tests/pipeline/test_chitchat_pipeline.py`
- `tests/pipeline/test_quiz_pipeline.py`
- `tests/pipeline/test_rag_pipeline.py`

### Дополнительные тесты
- `tests/addititional/diagnose_network.py` — диагностика сети
- `test_reformat.py` — тест переформатирования LaTeX

## Производительность
- **Создание сессии**: < 1 мс
- **Запуск задачи**: 2-5 сек (зависит от внешних сервисов)
- **Уведомление UI**: < 5 сек (с таймаутом)
- **Очистка сессий**: < 100 мс (100 сессий)
- **RAG search**: 1-3 сек
- **Generate exam**: 3-10 сек
- **Grade exam**: 1-2 сек

## Безопасность и ограничения
- **Ограничение параллелизма**: 2 сессии (настраивается)
- **TTL сессий**: 600 секунд (10 минут)
- **Таймаут UI уведомлений**: 5 секунд
- **Таймаут внешних сервисов**: 60 секунд
- **Максимум событий в истории**: 200

## Важные паттерны
1. **Async/await** — все I/O операции асинхронные
2. **MemorySaver** — сохранение состояния между сообщениями
3. **Fire-and-forget** — уведомления UI без ожидания
4. **Session-based** — изоляция состояния по сессиям
5. **Event-driven** — прогресс через события
6. **Pydantic** — валидация и структурирование данных