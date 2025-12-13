Да, именно для таких сценариев **LangGraph** и создавался. Ваш текущий подход (простой `if/else` внутри одной функции) работает для простых задач, но чтобы реализовать сложную логику (планирование -\> поиск -\> выбор ветки -\> генерация/квиз -\> оценка), нужно разбить процесс на **отдельные узлы (nodes)**.

Главное изменение — это перенос логики принятия решений из кода инструмента в **состояние (State)** и **ребра (Edges)** графа.

Вот как можно архитектурно реализовать ваш запрос:

### 1\. Расширяем State (Память графа)

Нам нужно хранить не только вопрос и ответ, но и промежуточные данные: найденные документы, тип задачи (ответ или квиз) и сам сгенерированный квиз.

```python
from typing import List, TypedDict, Literal, Optional

class AgentState(TypedDict):
    question: str                 # Вопрос пользователя
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz"] # Намерение
    documents: List[str]          # Найденные материалы RAG
    quiz_content: Optional[str]   # Сгенерированный квиз (если был нужен)
    user_solution: Optional[str]  # Ответ пользователя на квиз (для оценки)
    final_answer: str             # Итоговый ответ агента
```

### 2\. Логика графа (Схема)

Мы построим граф, который работает по вашей логике:

1.  **Planner (Router):** Анализирует запрос. Это просто болтовня? Нужен поиск? Это запрос на квиз? Или пользователь прислал ответы на квиз?
2.  **Retriever:** Если нужен RAG, идем сюда.
3.  **Decision Maker:** Смотрим на `intent`.
      * Если `rag_answer` -\> идем в **Generator**.
      * Если `generate_quiz` -\> идем в **QuizCreator**.
      * Если `evaluate_quiz` -\> идем в **QuizGrader**.

### 3\. Полный код реализации

Вот пример того, как переписать ваш код под новую структуру:

```python
from typing import TypedDict, Literal, List, Optional
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

# Импорты ваших сервисов (заглушки для примера)
# from settings import get_settings
# from llm_service.llm_client import LLMClient

# --- ЗАГЛУШКИ ДЛЯ ПРИМЕРА (чтобы код работал при копировании) ---
class MockLLM:
    def generate(self, prompts, **kwargs):
        return ["Mock response based on prompt"]
    def structured_predict(self, text):
        # Простая эвристика для примера роутинга
        if "квиз" in text.lower() and "решение" in text.lower(): return "evaluate_quiz"
        if "квиз" in text.lower(): return "generate_quiz"
        if "поиск" in text.lower() or "rag" in text.lower(): return "rag_answer"
        return "general"

client = MockLLM()
def rag_search_tool(query): return ["Документ 1: Python это язык...", "Документ 2: LangGraph это библиотека..."]
# ---------------------------------------------------------------

# 1. СОСТОЯНИЕ
class AgentState(TypedDict):
    question: str
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz"]
    documents: List[str]
    quiz_data: Optional[str]
    final_answer: str

# 2. УЗЛЫ (NODES)

def planner_node(state: AgentState) -> AgentState:
    """Анализирует запрос и определяет план действий (intent)."""
    question = state["question"]
    print(f"--- PLANNER: Анализ запроса '{question}' ---")
    
    # В реальности здесь вызов LLM, который классифицирует запрос
    # prompt = f"Classify intent: {question}. Options: general, rag_answer, generate_quiz, evaluate_quiz"
    intent = client.structured_predict(question)
    
    return {"intent": intent}

def retrieve_node(state: AgentState) -> AgentState:
    """Ищет документы в RAG."""
    print("--- RETRIEVER: Поиск документов ---")
    query = state["question"]
    docs = rag_search_tool(query)
    return {"documents": docs}

def direct_answer_node(state: AgentState) -> AgentState:
    """Отвечает без инструментов (болтовня)."""
    print("--- DIRECT: Простой ответ ---")
    return {"final_answer": "Я могу просто поговорить с вами, но для фактов используйте RAG."}

def rag_answer_node(state: AgentState) -> AgentState:
    """Генерирует ответ на основе документов."""
    print("--- GENERATOR: Ответ по документам ---")
    context = "\n".join(state["documents"])
    # prompt = f"Context: {context}. Question: {state['question']}"
    # answer = client.generate([prompt])
    answer = f"Вот ответ на основе {len(state['documents'])} документов..."
    return {"final_answer": answer}

def create_quiz_node(state: AgentState) -> AgentState:
    """Создает квиз на основе документов."""
    print("--- QUIZ MAKER: Генерация квиза ---")
    context = "\n".join(state["documents"])
    # prompt = f"Make a quiz based on: {context}"
    # quiz = client.generate([prompt])
    quiz = "Вопрос 1: Что такое LangGraph? (A) Еда (B) Библиотека"
    # Мы сохраняем квиз в state, и выдаем его пользователю
    return {"quiz_data": quiz, "final_answer": quiz}

def evaluate_quiz_node(state: AgentState) -> AgentState:
    """Оценивает решение пользователя (предполагаем, что документы уже есть или не нужны)."""
    print("--- QUIZ GRADER: Оценка решения ---")
    # Здесь логика сложнее: нам нужно знать, какой был квиз.
    # В чат-ботах это решается через память (checkpointer), здесь упростим.
    feedback = "Вы ответили верно! (Это заглушка оценки)"
    return {"final_answer": feedback}

# 3. ПОСТРОЕНИЕ ГРАФА

def route_after_planner(state: AgentState):
    """Решает, куда идти после планирования."""
    intent = state["intent"]
    if intent == "general":
        return "direct_answer"
    elif intent == "evaluate_quiz":
        # Если оценка, нам, возможно, не нужен поиск, или нужен (зависит от логики)
        return "evaluate_quiz"
    else:
        # Для rag_answer и generate_quiz сначала нужны данные
        return "retrieve"

def route_after_retriever(state: AgentState):
    """Решает, что делать с полученными данными."""
    intent = state["intent"]
    if intent == "generate_quiz":
        return "create_quiz"
    else:
        return "rag_answer"

workflow = StateGraph(AgentState)

# Добавляем узлы
workflow.add_node("planner", planner_node)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("direct_answer", direct_answer_node)
workflow.add_node("rag_answer", rag_answer_node)
workflow.add_node("create_quiz", create_quiz_node)
workflow.add_node("evaluate_quiz", evaluate_quiz_node)

# Строим связи
workflow.add_edge(START, "planner")

# Условное ребро от планера
workflow.add_conditional_edges(
    "planner",
    route_after_planner,
    {
        "direct_answer": "direct_answer",
        "retrieve": "retrieve",
        "evaluate_quiz": "evaluate_quiz"
    }
)

# Условное ребро от ретривера
workflow.add_conditional_edges(
    "retrieve",
    route_after_retriever,
    {
        "rag_answer": "rag_answer",
        "create_quiz": "create_quiz"
    }
)

# Все ветки ведут в конец
workflow.add_edge("direct_answer", END)
workflow.add_edge("rag_answer", END)
workflow.add_edge("create_quiz", END)
workflow.add_edge("evaluate_quiz", END)

# Компиляция
app = workflow.compile()
```

### Как это работает "вживую"?

#### Сценарий 1: "Создай квиз по LangGraph"

1.  **Planner:** Видит слово "квиз", ставит `intent="generate_quiz"`.
2.  **Edge:** Направляет в `retrieve`.
3.  **Retrieve:** Идет в базу знаний, достает текст про LangGraph. Сохраняет в `state["documents"]`.
4.  **Edge:** Видит `intent="generate_quiz"`, направляет в `create_quiz`.
5.  **Create Quiz:** Генерирует вопросы. Выдает результат.
6.  **END**.

#### Сценарий 2: "Вот мои ответы на квиз..."

*Важный нюанс:* Чтобы это сработало, бот должен помнить, какой квиз он вам задавал. В LangGraph для этого используется **Checkpointer** (память треда).

Если вы используете память (`MemorySaver`), то граф "засыпает" на `END` после выдачи квиза. Когда пользователь пишет ответ:

1.  Загружается старый State (где уже лежит `quiz_data`).
2.  **Planner:** Видит "ответы", ставит `intent="evaluate_quiz"`.
3.  **Edge:** Направляет в `evaluate_quiz`.
4.  **Evaluate Quiz:** Берет `state["quiz_data"]` (из памяти) и новый `question` (ответ пользователя), сравнивает и дает фидбек.

### Ключевые отличия от вашего текущего кода

1.  **Явное планирование:** Вместо `if "rag" in question` вы используете LLM в узле `Planner`, чтобы понять намерение. Это позволяет ловить сложные фразы типа "проверь мои знания по этой теме".
2.  **Разделение ответственности:** Узел генерации квиза ничего не знает про поиск. Он просто берет документы из `state["documents"]`. Это делает код чище.
3.  **Гибкость:** Вы легко можете добавить шаг "Проверка качества документов" после `retrieve` перед генерацией, просто вставив новый узел в граф.

Отличный вопрос\! Подключение памяти (или **Checkpointer** в терминологии LangGraph) — это критический шаг для сценария с квизами. Без него агент "забудет", какой вопрос он задал, сразу после того, как отдаст ответ пользователю.

В LangGraph память работает не как простой список сообщений, а как **сохранение слепков состояния (State snapshots)** на каждом шаге.

Вот как это делается.

### 1\. Основная идея

1.  Мы используем класс `MemorySaver` (для хранения в RAM) или `SqliteSaver`/`PostgresSaver` (для базы данных).
2.  Передаем его в метод `.compile(checkpointer=memory)`.
3.  При вызове агента (`invoke`) **обязательно** передаем `thread_id`. По этому ID агент находит прошлое состояние.

### 2\. Реализация на примере "Квиз -\> Оценка"

Допустим, у нас простой граф: если квиза нет — создаем, если квиз уже есть в памяти — оцениваем ответ пользователя.

```python
from typing import TypedDict, Optional, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver # <--- 1. Импорт чекерпоинтера

# --- Состояние ---
class QuizState(TypedDict):
    question: str           # Последнее сообщение пользователя
    quiz_question: Optional[str] # Вопрос квиза (сохраняется между ходами)
    correct_answer: Optional[str] # Правильный ответ (скрыт в памяти)
    feedback: Optional[str] # Обратная связь

# --- Узлы ---

def router_node(state: QuizState):
    """Решает: мы создаем квиз или проверяем его?"""
    # Если в памяти уже есть правильный ответ, значит, мы ждем решение от юзера
    if state.get("correct_answer"):
        return "grade_quiz"
    else:
        return "generate_quiz"

def generate_quiz_node(state: QuizState):
    """Генерирует вопрос и запоминает правильный ответ."""
    print("--- АГЕНТ: Генерирую квиз... ---")
    # (Здесь был бы вызов LLM)
    q = "Сколько будет 2 + 2?"
    a = "4"
    
    return {
        "quiz_question": q,
        "correct_answer": a,
        "feedback": f"Ваш вопрос: {q}"
    }

def grade_quiz_node(state: QuizState):
    """Сравнивает ответ пользователя с сохраненным правильным ответом."""
    print("--- АГЕНТ: Проверяю ответ... ---")
    user_ans = state["question"].strip() # Ответ пользователя из текущего сообщения
    correct = state["correct_answer"]    # Достаем из памяти!
    
    if user_ans == correct:
        msg = "Правильно! Молодец."
    else:
        msg = f"Неверно. Правильный ответ был: {correct}"
        
    # Очищаем состояние квиза, чтобы в следующий раз начать новый
    return {
        "feedback": msg,
        "quiz_question": None, 
        "correct_answer": None
    }

# --- Сборка графа ---

builder = StateGraph(QuizState)

builder.add_node("router", router_node)
builder.add_node("generate_quiz", generate_quiz_node)
builder.add_node("grade_quiz", grade_quiz_node)

builder.add_edge(START, "router")
builder.add_conditional_edges("router", router_node) # Функция сама вернет имя следующего узла
builder.add_edge("generate_quiz", END)
builder.add_edge("grade_quiz", END)

# <--- 2. Инициализация памяти и компиляция --->
memory = MemorySaver()
app = builder.compile(checkpointer=memory)
```

### 3\. Как это запускать (симуляция диалога)

Самое важное здесь — параметр `config` с ключом `thread_id`. Пока `thread_id` одинаковый, агент помнит контекст.

```python
# --- ХОД 1: Пользователь просит квиз ---
thread_config = {"configurable": {"thread_id": "session_123"}}

print("\n=== ХОД 1 ===")
user_input = "Хочу решить задачу"
# Передаем config, чтобы сохранить состояние после выполнения
result = app.invoke({"question": user_input}, config=thread_config)
print(f"Бот: {result['feedback']}")

# В этот момент в памяти (memory) для session_123 лежит:
# correct_answer = "4"

# --- ХОД 2: Пользователь отвечает ---
print("\n=== ХОД 2 ===")
user_input = "4" 
# Используем ТОТ ЖЕ thread_id
result = app.invoke({"question": user_input}, config=thread_config)
print(f"Бот: {result['feedback']}")
```

### Вывод в консоли будет таким:

```text
=== ХОД 1 ===
--- АГЕНТ: Генерирую квиз... ---
Бот: Ваш вопрос: Сколько будет 2 + 2?

=== ХОД 2 ===
--- АГЕНТ: Проверяю ответ... ---
Бот: Правильно! Молодец.
```

### Важные нюансы

1.  **MemorySaver хранит всё в RAM:** Если вы перезапустите скрипт (остановите Python процесс), память очистится.

2.  **Для продакшена (База данных):**
    Вам нужно заменить `MemorySaver` на персистентное хранилище, чтобы память жила даже после перезагрузки сервера. LangGraph поддерживает SQLite и Postgres из коробки.

    ```python
    # Пример для SQLite (файловая БД)
    from langgraph.checkpoint.sqlite import SqliteSaver
    import sqlite3

    conn = sqlite3.connect("my_agent_memory.db", check_same_thread=False)
    memory = SqliteSaver(conn)

    app = builder.compile(checkpointer=memory)
    ```

3.  **Human-in-the-loop (Человек в цикле):**
    Благодаря чекпоинтеру вы также можете реализовать функцию "прерывания". Например, агент сгенерировал квиз, но перед отправкой вы (как админ) хотите посмотреть его. Вы можете поставить `interrupt_before=["generate_quiz"]`, и граф остановится, сохранит состояние и будет ждать подтверждения.

### Резюме для вашей архитектуры

В вашем классе `AgentSystem`:

1.  В `__init__` создайте `self.memory = MemorySaver()`.
2.  В `_build_graph` добавьте `checkpointer=self.memory` при компиляции.
3.  В методе `run(self, question: str)` измените сигнатуру, чтобы принимать `session_id` (или генерировать его), и передавайте его в `invoke`:
    ```python
    def run(self, question: str, session_id: str = "default") -> str:
        config = {"configurable": {"thread_id": session_id}}
        final_state = self.app.invoke({"question": question}, config=config)
        # ...
    ```

Теперь ваш роутер (Planner) сможет заглянуть в `state` и увидеть: "Ого, поле `quiz_content` не пустое, значит, пользователь сейчас прислал мне ответ на квиз, а не просто текст. Направлю-ка я его в узел `EvaluateQuiz`".