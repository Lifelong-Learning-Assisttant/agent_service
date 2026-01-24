# Технический анализ: Реализация Supervisor + Subgraphs в NetRunner (2026)

## Контекст
Данный документ описывает технические детали реализации модульной архитектуры NetRunner, основанной на паттерне **"Router-driven Subgraphs"** с использованием LangGraph (версии 2025-2026). Архитектура решает проблемы изоляции контекста, управления инструментами и персистентности состояния.

## 1. Стратегия управления состоянием: Scoped State

Использование **Monolithic State** (единого TypedDict для всего) признано антипаттерном. Мы внедряем **Scoped State** с явным маппингом данных при переходах.

### Архитектура Состояний

1.  **GlobalState (Supervisor Level)**:
    *   Хранит данные, необходимые для маршрутизации и профилирования пользователя.
    *   `messages`: Глобальная история сообщений (Append-only).
    *   `user_profile`: Долгосрочные данные (компетенции, предпочтения).
    *   `active_mode`: Текущий режим (Quiz, Algo, Chat).
    *   `next_agent`: Указатель на следующий шаг.

2.  **Scoped States (Subgraph Level)**:
    *   **QuizState**: `{ messages, topic, difficulty, current_question_index, score, feedback }`.
    *   **AlgoState**: `{ messages, problem_id, user_code, attempts_count, hints_given }`.
    *   **ChatState**: `{ messages, search_results }`.

### Реализация перехода (Mapping)

Передача данных между Supervisor и Subgraph происходит через функцию-обертку узла:

```python
# Пример (псевдокод реализации в LangGraph)
def call_quiz_subgraph(state: GlobalState):
    # 1. Map Global -> Scoped (Вход)
    # Инициализируем подграф данными из глобального профиля
    quiz_input = {
        "messages": state["messages"][-1:], # Передаем только последний запрос
        "topic": state["user_profile"].get("interested_topic"),
        "difficulty": "hard",
        "current_question_index": state["user_profile"].get("quiz_progress", 0) # Восстановление прогресса
    }
    
    # 2. Invoke Subgraph
    # quiz_app - скомпилированный StateGraph
    quiz_output = quiz_app.invoke(quiz_input)
    
    # 3. Map Scoped -> Global (Выход)
    # Обновляем глобальное состояние результатами работы подграфа
    return {
        "messages": [AIMessage(content=quiz_output["feedback"])],
        "user_profile": {
            "last_quiz_score": quiz_output.get("score"),
            "quiz_progress": quiz_output.get("current_question_index") # Сохраняем прогресс
        }
    }
```

## 2. Изоляция Инструментов (Tool Isolation)

Инструменты привязываются строго к агентам внутри подграфов. Это гарантирует, что "Болталка" физически не может вызвать инструмент оценки квиза.

```python
# Quiz Subgraph Definition
quiz_tools = [grade_submission_tool, generate_code_problem_tool]
quiz_agent = create_react_agent(model, quiz_tools)

# Chat Subgraph Definition
chat_tools = [web_search_tool, rag_search_tool] 
chat_agent = create_react_agent(model, chat_tools)
```

## 3. Паттерны передачи управления (Handoff Patterns)

Для выхода из подграфа (например, пользователь попросил сменить тему) используется механизм `Command`.

**Сценарий:** Пользователь внутри квиза пишет "Хватит, давай поговорим про погоду".

```python
from langgraph.types import Command, Literal

def quiz_agent_node(state: QuizState) -> Command[Literal["supervisor"]]:
    response = model.invoke(state["messages"])
    
    # Если агент распознал намерение выхода
    if check_exit_intent(response):
        return Command(
            graph=Command.PARENT,           # Адресат: Родительский граф
            goto="supervisor_node",         # Узел назначения
            update={"next_agent": "chat_agent"} # Обновление состояния родителя
        )
    
    return {"messages": [response]}
```

## 4. Персистентность и "Cold Start" (Memory Persistence)

Для поддержки длительных пауз (пользователь вернулся через день) используется двухуровневая стратегия:

1.  **LangGraph Checkpointing**: Основной механизм сохранения состояния потока выполнения (`thread_id`).
2.  **Explicit State Snapshotting**: Критические данные (прогресс квиза, текущая задача) дублируются в `user_profile` глобального состояния при каждом выходе из подграфа.

При повторном входе в подграф (`call_quiz_subgraph`), состояние инициализируется из `user_profile`, что позволяет продолжить с того же места, даже если локальный стейт подграфа был очищен.

## Резюме для реализации

1.  Создать отдельные классы `TypedDict` для `GlobalState` и каждого подграфа.
2.  Реализовать функции-мапперы для входа и выхода из подграфов.
3.  Использовать `Command(graph=Command.PARENT)` для реализации кнопки "Стоп" и смены режима.
4.  Обновлять `user_profile` в глобальном состоянии после каждого значимого действия в подграфе.