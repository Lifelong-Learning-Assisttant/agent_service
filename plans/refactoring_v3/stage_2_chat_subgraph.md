# Этап 2: Chat Subgraph (Режим общения)

## Цель
Реализовать подграф для свободного общения (`Chat Subgraph`). Он должен отличать обычную болтовню (chitchat) от технических вопросов, требующих поиска, и использовать `Shared Retrieval Subgraph` как инструмент.

## Задачи

### 1. Реализация узлов (Nodes)
- [ ] **Chat Router Node**:
    - Классифицирует входное сообщение: `general` (болтовня) vs `technical` (вопрос по теме).
- [ ] **Direct Answer Node**:
    - Генерирует быстрый ответ для `general` интентов, используя системный промпт и контекст беседы.
- [ ] **Full Answer Node**:
    - Формирует развернутый ответ на основе материалов, полученных от `Shared Retrieval`.
    - Добавляет ссылки на источники.

### 2. Интеграция с Retrieval
- [ ] Настроить вызов `Shared Retrieval Subgraph` как вложенного графа или через вызов функции (в зависимости от ограничений LangGraph).
- [ ] Обеспечить передачу `prepared_material` из Retrieval в Full Answer.

### 3. Сборка графа
- [ ] Определить `StateGraph` для Chat.
- [ ] Настроить ветвление:
    - `Start` -> `Chat Router`
    - `Chat Router` --(general)--> `Direct Answer` -> `End`
    - `Chat Router` --(technical)--> `Retrieval Subgraph` -> `Full Answer` -> `End`

### 4. Тестирование
- [ ] Создать тест сценария: `agent_service/tests/scenarios/test_chat_graph.py`.
- [ ] Проверить сценарии:
    - "Привет, как дела?" -> Direct Answer.
    - "Как работает трансформер?" -> Retrieval -> Full Answer.
    - Сохранение контекста беседы (Memory).

## Ожидаемый результат
Модуль `chat.py`, экспортирующий `chat_graph`.