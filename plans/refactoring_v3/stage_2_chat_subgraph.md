# Этап 2: Chat Subgraph (Режим общения)

## Цель
Реализовать подграф для свободного общения (`Chat Subgraph`). Он должен отличать обычную болтовню (chitchat) от технических вопросов, требующих поиска, и использовать `Shared Retrieval Subgraph` как инструмент.

## Задачи
### 1. Реализация узлов (Nodes)
- [x] **Chat Router Node**:
    - Классифицирует входное сообщение: `general` (болтовня) vs `technical` (вопрос по теме).
- [x] **Direct Answer Node**:
    - Генерирует быстрый ответ для `general` интентов, используя системный промпт и контекст беседы.
- [x] **Full Answer Node**:
    - Формирует развернутый ответ на основе материалов, полученных от `Shared Retrieval`.
    - Добавляет ссылки на источники.

### 2. Интеграция с Retrieval
- [x] Настроить вызов `Shared Retrieval Subgraph` как вложенного графа или через вызов функции (в зависимости от ограничений LangGraph).
- [x] Обеспечить передачу `prepared_material` из Retrieval в Full Answer.

### 3. Сборка графа
- [x] Определить `StateGraph` для Chat.
- [x] Настроить ветвление:
    - `Start` -> `Chat Router`
    - `Chat Router` --(general)--> `Direct Answer` -> `End`
    - `Chat Router` --(technical)--> `Retrieval Subgraph` -> `Full Answer` -> `End`

### 4. Тестирование и Стабилизация
- [x] Создать тест сценария: `agent_service/tests/scenarios/test_chat_graph.py`.
- [x] Проверить сценарии:
    - "Привет, как дела?" -> Direct Answer.
    - "Как работает трансформер?" -> Retrieval -> Full Answer.
    - Сохранение контекста беседы (Memory).
- [x] **Устранение проблем с таймаутами**:
    - Исправлена ошибка `ConnectTimeout` при работе с `api.ai-mediator.ru` внутри Docker.
    - В `agent_service/Dockerfile-dev` добавлены `curl` и `ca-certificates`.
    - Обновлена библиотека `httpcore` (откат на стабильную версию или обновление для корректной работы с HTTP/2).
    - Проведены нагрузочные тесты и тесты производительности (`test_llm_client_perf.py`).

## Ожидаемый результат
Модуль `chat.py`, экспортирующий `chat_graph`. Стабильно работающие тесты без таймаутов.