# Документация по агенту

## Обзор

Агент — это система на основе LangGraph, которая поддерживает сложные сценарии взаимодействия, включая простые разговоры, работу с RAG (Retrieval-Augmented Generation) и генерацию/оценку квизов.

Начиная с версии 2.0, агент поддерживает **множественные сессии** с автоматическим управлением состоянием, ограничением параллелизма и реальными уведомлениями в Web UI.

Начиная с версии 2.1, добавлены **асинхронные версии инструментов** для неблокирующих вызовов внешних сервисов.

## Архитектура

### Система сессий

Агент использует `AgentSession` для управления каждой отдельной сессией:

```mermaid
graph TD
    A[Web UI] -->|create_session| B[AgentSystem]
    B -->|create| C[AgentSession UUID-1]
    B -->|create| D[AgentSession UUID-2]
    C -->|notify_ui| A
    D -->|notify_ui| A
    C -->|call_tool| E[RAG/Test Generator]
    D -->|call_tool| E
```

### Ключевые компоненты

#### 1. **AgentSession**
Отвечает за управление одной сессией:
- Состояние: `state`, `task`, `last_active_at`, `created_at`, `last_events`
- Управление жизненным циклом: `start()`, `cancel()`, `cleanup()`
- Уведомления UI: `notify_ui()` с fire-and-forget (timeout 5 сек)
- Вызов инструментов: `call_tool()` с прогресс-уведомлениями

**Источник:** `agent_service/agent_session.py`

#### 2. **AgentSystem**
Централизованный менеджер сессий:
- Sessions map: `sessions: Dict[str, AgentSession]`
- Ограничение параллелизма: `session_semaphore: Semaphore`
- Методы: `create_session()`, `get_session()`, `remove_session()`, `sweep_expired_sessions()`, `run()`

**Источник:** `agent_service/agent_system.py`

### Граф состояний

```mermaid
graph TD
    A[Start] --> B[Planner]
    B -->|general| C[Direct Answer]
    B -->|rag_answer| D[Retrieve]
    B -->|generate_quiz| D[Retrieve]
    B -->|evaluate_quiz| E[Evaluate Quiz]
    D -->|rag_answer| F[RAG Answer]
    D -->|generate_quiz| G[Create Quiz]
    C --> H[End]
    F --> H[End]
    G --> H[End]
    E --> H[End]
```

**Узлы:**
- **Planner**: Определяет намерение пользователя
- **Retrieve**: Выполняет поиск через RAG
- **Direct Answer**: Отвечает на общие вопросы
- **RAG Answer**: Генерирует ответ по документам
- **Create Quiz**: Создает квиз
- **Evaluate Quiz**: Оценивает ответы

## Async инструменты

### Доступные async-инструменты

**Источник:** `agent_service/langchain_tools.py`

```python
from langchain_tools import (
    rag_search_async,
    rag_generate_async,
    generate_exam_async,
    grade_exam_async
)
```

#### 1. `rag_search_async(query, top_k, use_hyde)`
Асинхронный поиск документов через RAG сервис.

**Пример:**
```python
result = await rag_search_async(
    query="машинное обучение",
    top_k=5,
    use_hyde=False
)
# Возвращает: JSON строку с результатами поиска
```

#### 2. `rag_generate_async(query, top_k, temperature, use_hyde)`
Асинхронная генерация ответа через RAG сервис.

**Пример:**
```python
result = await rag_generate_async(
    query="Объясни ML",
    top_k=5,
    temperature=0.7,
    use_hyde=False
)
# Возвращает: JSON строку с ответом
```

#### 3. `generate_exam_async(markdown_content, config)`
Асинхронная генерация экзамена через test_generator.

**Пример:**
```python
config = {
    "total_questions": 5,
    "single_choice_count": 3,
    "multiple_choice_count": 1,
    "open_ended_count": 1,
    "provider": "local"
}

result = await generate_exam_async(
    markdown_content="# Python Basics\n...",
    config=config
)
# Возвращает: JSON строку с экзаменом
```

#### 4. `grade_exam_async(exam_id, answers)`
Асинхронная оценка ответов на экзамен.

**Пример:**
```python
answers = [
    {"question_id": "q1", "choice": [0]},
    {"question_id": "q2", "text_answer": "Ответ"}
]

result = await grade_exam_async(
    exam_id="ex-123",
    answers=answers
)
# Возвращает: JSON строку с результатами оценки
```

### Инфраструктура

**Настройки:**
- `test_generator_service_url`: `http://api:52812`
- `http_timeout_s`: таймаут HTTP запросов
- Docker сеть: `test_generator_default`

**Зависимости:**
- `httpx` — для async HTTP запросов

### Использование в AgentSession

```python
async def _run_graph(self, question):
    # Шаг 1: Планирование
    await self.notify_ui(step="planning", message="Создаю план...")
    
    # Шаг 2: Поиск (async)
    rag_result = await rag_search_async(query=question, top_k=5)
    
    # Шаг 3: Генерация экзамена (async)
    exam = await generate_exam_async(markdown_content, config)
    
    # Шаг 4: Оценка (async)
    grade = await grade_exam_async(exam.exam_id, answers)
    
    return grade
```

### Совместимость

Сохранены sync версии для обратной совместимости:
```python
# Sync (старый вариант)
from langchain_tools import rag_search, generate_exam

# Async (новый вариант)
from langchain_tools import rag_search_async, generate_exam_async
```

### Тестирование

**Результаты:**
```
Генерируем экзамен...
✅ Сгенерирован экзамен: ex-0ec33740

Оцениваем ответы...
✅ Результаты оценки:
   Счет: 75.0 %
   Правильно: 1 / 2
```

**Подробности:** см. `agent_service/docs/async_tools_setup.md`

## Управление сессиями

### Создание и запуск

```python
from agent_system import AgentSystem

agent = AgentSystem()

# Создание сессии
session_id = agent.create_session()

# Запуск задачи
result = await agent.run(
    question="Создай квиз по машинному обучению",
    session_id=session_id
)
```

### Уведомления в Web UI

Система автоматически отправляет уведомления на URL из конфига:

**Типы уведомлений:**
- `start` — начало выполнения
- `progress` — промежуточный результат
- `done` — завершение успешно
- `error` — ошибка выполнения
- `cancelled` — отмена пользователем

**Формат:**
```json
{
  "session_id": "uuid-1",
  "step": "rag_search",
  "message": "Поиск документов...",
  "tool": "rag_search",
  "level": "info",
  "meta": {"query": "машинное обучение"},
  "timestamp": "2025-12-25T13:00:00Z"
}
```

### Управление ресурсами

#### Очистка протухших сессий

```python
# Автоматическая очистка (внутри run())
agent.sweep_expired_sessions()

# Ручная очистка
agent.sweep_expired_sessions(force=True)
```

**Параметры:**
- `session_ttl_seconds`: 600 (10 минут) из конфига
- Удаляет сессии без активности > 10 минут

#### Ограничение параллелизма

Максимум 3 сессии одновременно (из конфига). При превышении создание блокируется.

## Конфигурация

### Настройки

**Источник:** `agent_service/settings.py`

```python
web_ui_url: str = "http://localhost:8150"
session_ttl_seconds: int = 600
concurrency_limit: int = 3
test_generator_service_url: str = "http://api:52812"
http_timeout_s: int = 30
```

### Конфигурационные файлы

**Источники:**
- `agent_service/app_settings-dev.json`
- `agent_service/app_settings-prod.json`

```json
{
  "web_ui_url": "http://localhost:8150",
  "session_ttl_seconds": 600,
  "concurrency_limit": 3,
  "test_generator_service_url": "http://api:52812",
  "http_timeout_s": 30
}
```

## Примеры использования

### Простой разговор

```python
agent = AgentSystem()
result = await agent.run("Привет! Как дела?", session_id="chitchat_session")
```

### Работа с RAG

```python
agent = AgentSystem()
result = await agent.run(
    "Расскажи о машинном обучении из учебника Яндекса",
    session_id="rag_session"
)
```

### Генерация и оценка квиза

```python
agent = AgentSystem()

# Генерируем квиз
quiz_result = await agent.run(
    "Создай квиз по машинному обучению",
    session_id="quiz_session"
)

# Оцениваем ответы (контекст сохраняется)
evaluation_result = await agent.run(
    "Вот мои ответы: ответ 1, ответ 2",
    session_id="quiz_session"
)
```

### Множественные сессии

```python
agent = AgentSystem()

# Сессия 1: Генерация квиза
session1 = agent.create_session()
await agent.run("Создай квиз по Python", session_id=session1)

# Сессия 2: RAG-ответ (параллельно)
session2 = agent.create_session()
await agent.run("Объясни ML", session_id=session2)
```

### Управление сессиями

```python
agent = AgentSystem()

# Создать сессию
session_id = agent.create_session()

# Проверить статус
session = agent.get_session(session_id)
if session:
    print(f"Активна: {session.is_running()}")
    print(f"Возраст: {session.get_age_seconds()} сек")

# Отменить выполнение
await agent.get_session(session_id).cancel()

# Удалить сессию
agent.remove_session(session_id)
```

## Безопасность и ограничения

### Ограничение параллелизма
- Максимум 3 сессии одновременно
- Используется `asyncio.Semaphore`

### Таймауты
- **UI уведомления**: 5 секунд на HTTP запрос
- **Сессия**: 10 минут без активности (TTL)
- **Инструменты**: Настраивается через `http_timeout_s` (по умолчанию 30 сек)

### Потокобезопасность
- `asyncio.Lock` для защиты состояния сессии
- `asyncio.Semaphore` для ограничения параллелизма
- `deque(maxlen=200)` для истории событий

## Логирование

Все компоненты логируют действия:

```bash
2025-12-25 13:00:00 | INFO | agent_system | Инициализация агента: provider=openai
2025-12-25 13:00:01 | INFO | agent_session | AgentSession created: uuid-1
2025-12-25 13:00:02 | INFO | agent_session | Start processing: uuid-1
2025-12-25 13:00:03 | INFO | agent_session | Tool call: rag_search
2025-12-25 13:00:05 | INFO | agent_session | UI notification sent: uuid-1
2025-12-25 13:00:10 | INFO | agent_session | Task completed: uuid-1
2025-12-25 16:00:00 | INFO | langchain_tools | Async calling test generator service at http://api:52812/api/generate
```

## Тестирование

### Unit тесты

```bash
docker run --rm -v $(pwd):/app -w /app agent_service_test uv run pytest tests/ -v
# Результат: 33/33 тестов ✅
```

**Покрытие:**
- `test_agent_session.py`: 18 тестов
- `test_agent_system_sessions.py`: 15 тестов

**Источники тестов:**
- `agent_service/tests/test_agent_session.py`
- `agent_service/tests/test_agent_system_sessions.py`

### Интеграционные тесты

См. `agent_service/tests/addititional/` и `agent_service/tests/components/` для тестов с внешними сервисами.

## Производительность

- **Создание сессии**: < 1 мс
- **Запуск задачи**: ~2-5 сек (зависит от RAG/генерации)
- **Уведомление UI**: < 5 сек (с таймаутом)
- **Очистка сессий**: < 100 мс (100 сессий)
- **RAG search**: 1-3 сек
- **Generate exam**: 3-10 сек
- **Grade exam**: 1-2 сек

## Миграция с v1.x

### Старый API (v1.x)
```python
agent = AgentSystem()
result = agent.run("question", session_id="session")
```

### Новый API (v2.x)
```python
agent = AgentSystem()
result = await agent.run("question", session_id="session")
```

**Изменения:**
- ✅ Автоматическое создание сессий
- ✅ Реальные уведомления в Web UI
- ✅ Ограничение параллелизма
- ✅ Автоматическая очистка
- ✅ Подробная история событий
- ✅ Async инструменты (v2.1)

## Заключение

Система сессий агента обеспечивает:

- **Масштабируемость**: Множество параллельных сессий
- **Надежность**: Автоматическое управление ресурсами
- **Прозрачность**: Реальные уведомления о прогрессе
- **Безопасность**: Ограничение параллелизма и таймауты
- **Гибкость**: Конфигурируемые параметры
- **Асинхронность**: Неблокирующие вызовы внешних сервисов

Для более подробной информации о тестировании агента, см. [Документация по тестам](test_documentation.md).
Для настройки async-инструментов, см. [Async tools setup](async_tools_setup.md).