У агента есть два инструмента:

1. для составления квизов

2. для проверки квизов

   

Ньанс в том, что инструмент составления квизов сразу отдает например 5 вопросов и ответы на них.

А агент должен:

1. создать например 5 вопрос используя инструмент генерации квизов

2. отправлять пользователю не все 5 вопросов одним сообщением (как сейчас и сразу с ответами).

А задавать их по одному и записывать к себе в память, ответы которые дает пользователь.

Затем произвести оценку квиза используя другой инструмент, изначальный квиз и ответы пользователя.

Отправить оценку квиза пользователю.

Быть готовым объяснить почему это правильный ответ, дать обратную связь

И перейти на начальный state графа после завершения квиза.


Для реализации интерактивного квиза, где вопросы задаются по одному, нам нужно существенно изменить логику работы **LangGraph** и способ хранения состояния в `AgentState`.

В текущей реализации граф линейный: `planner` -> `retrieve` -> `create_quiz` -> `END`. Чтобы сделать его цикличным и интерактивным, нам нужно добавить "память" о текущем прогрессе квиза.

Вот план изменений и пример реализации:

---

### 1. Обновление состояния (`AgentState`)

Нам нужно добавить поля для отслеживания текущего вопроса, списка всех вопросов и ответов пользователя.

```python
class AgentState(TypedDict, total=False):
    question: str
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"]
    documents: List[str]
    
    # Новые поля для квиза
    quiz_questions: List[Dict[str, str]]  # Список объектов {"q": "...", "a": "..."}
    current_quiz_index: int               # Индекс текущего вопроса
    user_answers: List[str]               # Ответы, которые дал пользователь
    
    final_answer: str

```

### 2. Изменение логики узлов

#### А. Узел генерации (`create_quiz_node`)

Теперь этот узел не просто возвращает текст, а парсит результат инструмента в список и задает первый вопрос.

```python
async def create_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
    context = "\n".join(state.get("documents", []))
    # Инструмент возвращает строку, ее нужно распарсить (например, в JSON или по разделителю)
    raw_quiz = await generate_exam_async(context)
    
    # Логика парсинга (зависит от формата вывода инструмента)
    # Предположим, мы получили список вопросов
    parsed_questions = self._parse_quiz(raw_quiz) 
    
    first_question = parsed_questions[0]["q"]
    
    if session:
        await session.notify_ui(step="quiz_start", message="Начинаем квиз!")

    return {
        **state,
        "quiz_questions": parsed_questions,
        "current_quiz_index": 0,
        "user_answers": [],
        "final_answer": f"Вопрос 1: {first_question}"
    }

```

#### Б. Узел обработки ответа (`process_quiz_answer_node`)

Этот узел будет записывать ответ пользователя и решать: задать следующий вопрос или перейти к оценке.

```python
async def process_quiz_answer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
    idx = state.get("current_quiz_index", 0)
    answers = state.get("user_answers", [])
    questions = state.get("quiz_questions", [])
    
    # Записываем ответ пользователя (он пришел в state["question"])
    answers.append(state["question"])
    new_idx = idx + 1
    
    if new_idx < len(questions):
        next_q = questions[new_idx]["q"]
        return {
            **state,
            "current_quiz_index": new_idx,
            "user_answers": answers,
            "final_answer": f"Вопрос {new_idx + 1}: {next_q}"
        }
    else:
        # Вопросы кончились, идем на оценку
        return {**state, "user_answers": answers, "intent": "evaluate_quiz"}

```

### 3. Обновление Роутинга и Планировщика

В `_determine_intent` нужно добавить проверку: если в состоянии уже есть `quiz_questions` и индекс меньше общего количества, значит пользователь сейчас **отвечает на квиз**, а не задает новый вопрос.

```python
def _determine_intent(self, state: AgentState) -> str:
    # Если квиз активен, принудительно ставим статус ответа
    if state.get("quiz_questions") and state.get("current_quiz_index", 0) < len(state["quiz_questions"]):
        # Но если пользователь явно просит "прекрати квиз", можно обработать тут
        return "quiz_answering"
    
    # Иначе — стандартная логика LLM...

```

### 4. Модификация структуры графа в `_build_graph`

Теперь граф должен поддерживать цикл:

```python
builder.add_node("process_answer", wrap_node(self.process_quiz_answer_node))

# Условные переходы после планировщика
builder.add_conditional_edges(
    "planner",
    self.route_after_planner,
    {
        "direct_answer": "direct_answer",
        "retrieve": "retrieve",
        "quiz_answering": "process_answer" # Новый путь
    }
)

# Условный переход после обработки ответа
builder.add_conditional_edges(
    "process_answer",
    lambda state: "evaluate_quiz" if state["intent"] == "evaluate_quiz" else END,
    {
        "evaluate_quiz": "evaluate_quiz",
        END: END
    }
)

```

### 5. Оценка и Обратная связь (`evaluate_quiz_node`)

После завершения квиза узел оценки должен сравнить `quiz_questions[i]["a"]` (правильный ответ) с `user_answers[i]`.

```python
async def evaluate_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
    # Формируем отчет для LLM: Вопрос - Правильный ответ - Ответ пользователя
    report = []
    for q, a in zip(state["quiz_questions"], state["user_answers"]):
        report.append(f"Q: {q['q']}\nCorrect: {q['a']}\nUser: {a}")
    
    # Вызываем инструмент оценки или LLM напрямую для подробной обратной связи
    feedback = await grade_exam_async("quiz_session", report)
    
    # Сбрасываем состояние квиза, чтобы можно было начать заново
    return {
        **state,
        "final_answer": feedback,
        "quiz_questions": [], # Очистка
        "current_quiz_index": 0,
        "user_answers": []
    }

```

### Что это дает:

1. **Пошаговость**: Пользователь получает 1 сообщение — 1 вопрос. Граф завершается (`END`), ожидая нового ввода.
2. **Память**: Благодаря `MemorySaver` в LangGraph, когда пользователь пишет ответ, агент загружает состояние по `thread_id` (session_id), видит, что это 3-й вопрос, и идет в `process_answer`.
3. **Обратная связь**: В финальном узле вы можете попросить LLM не просто поставить оценку, а "объяснить ошибки в стиле учителя".

Ниже представлен обновленный код для `agent_service/agent_system.py`. Основные изменения коснулись структуры состояния `AgentState`, логики планировщика и добавления нового узла для обработки ответов в цикле.

### Основные изменения в логике

1. **Состояние (State)**: Добавлены поля `quiz_questions` (хранение списка вопросов и ответов), `current_quiz_index` (счетчик) и `user_answers` (хранилище ответов пользователя).
2. **Интерактивность**: Вместо выдачи всего квиза сразу, узел `create_quiz` теперь инициализирует сессию и выдает только первый вопрос.
3. **Цикличность**: Добавлен узел `process_quiz_answer`, который по цепочке опрашивает пользователя, пока список вопросов не исчерпается.
4. **Оценка и переход**: После последнего вопроса автоматически вызывается `evaluate_quiz`, который дает развернутую обратную связь, после чего состояние квиза очищается для возврата в начальную точку.

---

### Обновленный `agent_service/agent_system.py`

```python
from typing import Dict, Optional, TypedDict, Literal, List, Any
import os
import asyncio
import json
from datetime import datetime, timezone

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from llm_service.llm_client import LLMClient
from settings import get_settings
from logger import get_logger
from langchain_tools import (
    make_async_tools, 
    rag_search_async, 
    rag_generate_async, 
    generate_exam_async, 
    grade_exam_async
)
from agent_session import AgentSession

# ---------- Обновленное состояние графа ----------
class AgentState(TypedDict, total=False):
    """Общее состояние исполнения графа."""
    question: str
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"]
    documents: List[str]
    
    # Поля для интерактивного квиза
    quiz_questions: List[Dict[str, str]]  # Список {"question": "...", "answer": "..."}
    current_quiz_index: int               # Индекс текущего вопроса
    user_answers: List[str]               # Ответы пользователя
    
    final_answer: str

class AgentSystem:
    def __init__(self, provider: Optional[str] = None) -> None:
        self.log = get_logger(__name__)
        cfg = get_settings()
        prov = provider or cfg.default_provider
        
        system_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
        system_prompt = ""
        if os.path.exists(system_prompt_path):
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip()
        
        self.client = LLMClient(provider=prov, system_prompt=system_prompt)
        self.cfg = cfg
        self.tools = make_async_tools()
        self.memory = MemorySaver()
        self.sessions: Dict[str, AgentSession] = {}
        
        # Ограничение параллелизма
        concurrency_limit = getattr(self.cfg, 'concurrency_limit', 2)
        self._concurrency_sem = asyncio.Semaphore(concurrency_limit)
        
        self.app = self._build_graph()

    # ---------- Узлы графа ----------

    async def planner_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Определяет, продолжаем ли мы квиз или анализируем новый запрос."""
        q = (state.get("question") or "").strip()
        
        # Если квиз уже начат, принудительно идем по пути ответов
        if state.get("quiz_questions") and state.get("current_quiz_index", 0) < len(state["quiz_questions"]):
            intent = "quiz_answering"
        else:
            intent = self._determine_intent(q)

        if session:
            await session.notify_ui(
                step="intent_determined",
                message=f"Намерение: {intent}",
                tool="planner",
                level="info",
                meta={"intent": intent}
            )

        return {**state, "intent": intent}

    async def create_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Генерирует квиз и задает ПЕРВЫЙ вопрос."""
        if session:
            await session.notify_ui(step="start_generate_exam", message="Подготовка вопросов квиза...", tool="generate_exam")

        context = "\n".join(state.get("documents", []))
        # Инструмент должен возвращать структурированный текст или JSON
        raw_quiz = await generate_exam_async(context)
        
        # Парсим вопросы (логика зависит от формата инструмента)
        # Здесь пример парсинга JSON, если инструмент его отдает
        try:
            quiz_data = json.loads(raw_quiz)
            questions = quiz_data if isinstance(quiz_data, list) else [quiz_data]
        except:
            # Если не JSON, просим LLM структурировать
            questions = await self._structurize_quiz_with_llm(raw_quiz)

        first_q = questions[0]["question"]
        
        return {
            **state,
            "quiz_questions": questions,
            "current_quiz_index": 0,
            "user_answers": [],
            "final_answer": f"Начинаем квиз! Вопрос 1:\n{first_q}"
        }

    async def process_quiz_answer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Записывает ответ и выдает СЛЕДУЮЩИЙ вопрос или переходит к оценке."""
        idx = state.get("current_quiz_index", 0)
        questions = state.get("quiz_questions", [])
        answers = state.get("user_answers", [])
        
        # Сохраняем текущий ответ пользователя
        answers.append(state.get("question", ""))
        new_idx = idx + 1
        
        if new_idx < len(questions):
            next_q = questions[new_idx]["question"]
            return {
                **state,
                "current_quiz_index": new_idx,
                "user_answers": answers,
                "final_answer": f"Принято. Вопрос {new_idx + 1}:\n{next_q}"
            }
        else:
            # Все вопросы пройдены
            return {
                **state,
                "user_answers": answers,
                "intent": "evaluate_quiz"
            }

    async def evaluate_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Финальная проверка, объяснение ошибок и сброс состояния."""
        if session:
            await session.notify_ui(step="start_grade_exam", message="Проверка ваших ответов...", tool="grade_exam")

        questions = state.get("quiz_questions", [])
        user_answers = state.get("user_answers", [])
        
        # Формируем данные для инструмента оценки
        eval_data = []
        for i, q_obj in enumerate(questions):
            eval_data.append({
                "question": q_obj["question"],
                "correct_answer": q_obj["answer"],
                "user_answer": user_answers[i]
            })

        # Вызываем инструмент оценки
        raw_feedback = await grade_exam_async("quiz_1", eval_data)
        
        # Просим LLM сделать ответ более дружелюбным и подробным (LaTeX support)
        prompt = (
            "На основе результатов квиза составь подробный разбор для ученика. "
            "Объясни, почему его ответы верны или нет. Используй LaTeX для формул. "
            f"Данные проверки: {raw_feedback}"
        )
        final_feedback = self.client.generate([prompt], temperature=0.3)[0]

        # Важно: Очищаем поля квиза в state, чтобы вернуться в "начальный state"
        return {
            **state,
            "final_answer": final_feedback,
            "quiz_questions": [],
            "current_quiz_index": 0,
            "user_answers": [],
            "intent": "general"
        }

    # ---------- Вспомогательные методы ----------

    async def _structurize_quiz_with_llm(self, text: str) -> List[Dict]:
        """Превращает сырой текст квиза в список объектов через LLM."""
        prompt = (
            "Преобразуй следующий текст квиза в JSON список объектов "
            "с полями 'question' и 'answer'. Верни ТОЛЬКО JSON.\n\n" + text
        )
        res = self.client.generate([prompt], temperature=0)[0]
        try:
            return json.loads(res)
        except:
            self.log.error("Failed to parse quiz JSON")
            return [{"question": "Ошибка загрузки вопроса", "answer": ""}]

    def _determine_intent(self, question: str) -> str:
        """Стандартное определение намерения (упрощено для примера)."""
        # (Используется логика из вашего исходного кода с PydanticModel)
        # Для краткости оставим заглушку, вызывающую вашу оригинальную логику
        return super()._determine_intent(question) if hasattr(super(), '_determine_intent') else "general"

    # ---------- Сборка графа ----------

    def _build_graph(self):
        builder = StateGraph(AgentState)
        
        def wrap_node(node_func):
            async def wrapped_node(state: AgentState, config: Optional[Dict] = None):
                session = config["configurable"].get("session") if config else None
                return await node_func(state, session)
            return wrapped_node

        builder.add_node("planner", wrap_node(self.planner_node))
        builder.add_node("retrieve", wrap_node(self.retrieve_node))
        builder.add_node("direct_answer", wrap_node(self.direct_answer_node))
        builder.add_node("rag_answer", wrap_node(self.rag_answer_node))
        builder.add_node("create_quiz", wrap_node(self.create_quiz_node))
        builder.add_node("process_answer", wrap_node(self.process_quiz_answer_node))
        builder.add_node("evaluate_quiz", wrap_node(self.evaluate_quiz_node))

        builder.add_edge(START, "planner")

        # Переходы после планировщика
        builder.add_conditional_edges(
            "planner",
            lambda s: s["intent"],
            {
                "general": "direct_answer",
                "rag_answer": "retrieve",
                "generate_quiz": "retrieve",
                "evaluate_quiz": "evaluate_quiz",
                "quiz_answering": "process_answer" # Если мы внутри квиза
            }
        )

        builder.add_conditional_edges(
            "retrieve",
            lambda s: "create_quiz" if s["intent"] == "generate_quiz" else "rag_answer",
            {
                "create_quiz": "create_quiz",
                "rag_answer": "rag_answer"
            }
        )

        # Переход после обработки ответа: либо к следующему вопросу (END и ждем ввода), 
        # либо к оценке (если intent сменился на evaluate_quiz)
        builder.add_conditional_edges(
            "process_answer",
            lambda s: "evaluate_quiz" if s["intent"] == "evaluate_quiz" else END,
            {
                "evaluate_quiz": "evaluate_quiz",
                END: END
            }
        )

        builder.add_edge("direct_answer", END)
        builder.add_edge("rag_answer", END)
        builder.add_edge("create_quiz", END)
        builder.add_edge("evaluate_quiz", END)

        return builder.compile(checkpointer=self.memory)

    # ... (остальные методы из agent_system.py без изменений)

```

### Как это работает для пользователя:

1. **Запрос**: "Хочу пройти тест по нейросетям".
2. **Агент**: Идет в `retrieve` -> `create_quiz`. Генерирует 5 вопросов, сохраняет их в `state`, но пишет в чат только: *"Вопрос 1: Что такое градиентный спуск?"*.
3. **Пользователь**: Пишет ответ.
4. **Агент**: `planner` видит, что в `state` есть активный квиз, и направляет запрос в `process_answer`. Тот сохраняет ответ, видит, что индекс 0 < 4, и пишет: *"Принято. Вопрос 2: ..."*.
5. **Финал**: После 5-го ответа `process_answer` меняет `intent` на `evaluate_quiz`. Узел оценки анализирует всё накопленное, выдает подробный разбор с формулами в LaTeX (например, ) и очищает квиз из памяти.
6. **Результат**: Агент снова готов к обычным вопросам или новому квизу.

Для реализации интерактивного квиза нам нужно изменить структуру состояния `AgentState` и логику переходов в графе. Основная идея в том, что после генерации вопросов агент переходит в режим ожидания ответов, сохраняя прогресс в `MemorySaver`.

Ниже представлен обновленный код для файла `agent_service/agent_system.py`, включающий все ваши требования:

```python
from typing import Dict, Optional, TypedDict, Literal, List, Any
import os
import asyncio
import json
from datetime import datetime, timezone

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from llm_service.llm_client import LLMClient
from settings import get_settings
from logger import get_logger
from langchain_tools import (
    make_async_tools, 
    rag_search_async, 
    rag_generate_async, 
    generate_exam_async, 
    grade_exam_async
)
from agent_session import AgentSession

# ---------- Обновленное состояние графа ----------
class AgentState(TypedDict, total=False):
    """Общее состояние исполнения графа."""
    question: str
    # Добавлен тип "quiz_answering" для процесса ответов
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"]
    documents: List[str]
    
    # Новые поля для интерактивного квиза
    quiz_questions: List[Dict[str, str]]  # Список объектов {"q": "...", "a": "..."}
    current_quiz_index: int               # Индекс текущего вопроса
    user_answers: List[str]               # Накопленные ответы пользователя
    
    final_answer: str

class AgentSystem:
    def __init__(self, provider: Optional[str] = None) -> None:
        self.log = get_logger(__name__)
        cfg = get_settings()
        prov = provider or cfg.default_provider
        
        system_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
        system_prompt = ""
        if os.path.exists(system_prompt_path):
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip()
        
        self.client = LLMClient(provider=prov, system_prompt=system_prompt)
        self.cfg = cfg
        self.tools = make_async_tools()
        
        # Память необходима для сохранения состояния между сообщениями пользователя
        self.memory = MemorySaver()
        self.sessions: Dict[str, AgentSession] = {}
        
        concurrency_limit = getattr(self.cfg, 'concurrency_limit', 2)
        self._concurrency_sem = asyncio.Semaphore(concurrency_limit)
        
        self.app = self._build_graph()

    # ---------- Узлы графа ----------

    async def planner_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Определяет, продолжаем ли мы квиз или анализируем новый запрос."""
        q = (state.get("question") or "").strip()
        
        # Если в памяти есть активный квиз и мы еще не задали все вопросы, 
        # считаем текущее сообщение ответом на вопрос.
        quiz_active = state.get("quiz_questions") is not None and len(state.get("quiz_questions", [])) > 0
        current_idx = state.get("current_quiz_index", 0)
        
        if quiz_active and current_idx < len(state["quiz_questions"]):
            intent = "quiz_answering"
        else:
            intent = self._determine_intent(q)

        if session:
            await session.notify_ui(
                step="intent_determined",
                message=f"Намерение: {intent}",
                tool="planner",
                level="info",
                meta={"intent": intent}
            )

        return {**state, "intent": intent}

    async def create_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Генерирует квиз и задает ПЕРВЫЙ вопрос."""
        if session:
            await session.notify_ui(step="start_generate_exam", message="Генерирую вопросы по материалам...", tool="generate_exam")

        context = "\n".join(state.get("documents", []))
        # Инструмент выдает 5 вопросов и ответов
        raw_quiz = await generate_exam_async(context)
        
        # Парсим результат инструмента в структурированный список (Helper-метод)
        questions = await self._parse_quiz_result(raw_quiz)
        
        first_q = questions[0]["q"]
        
        return {
            **state,
            "quiz_questions": questions,
            "current_quiz_index": 0,
            "user_answers": [],
            "final_answer": f"Начинаем квиз! Вопрос №1:\n{first_q}"
        }

    async def process_quiz_answer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Записывает ответ пользователя и выдает СЛЕДУЮЩИЙ вопрос."""
        idx = state.get("current_quiz_index", 0)
        questions = state.get("quiz_questions", [])
        answers = state.get("user_answers", [])
        
        # 1. Сохраняем ответ пользователя на ТЕКУЩИЙ вопрос
        user_reply = state.get("question", "")
        answers.append(user_reply)
        
        # 2. Переходим к следующему индексу
        next_idx = idx + 1
        
        if next_idx < len(questions):
            # Если есть еще вопросы — задаем следующий
            next_q = questions[next_idx]["q"]
            return {
                **state,
                "current_quiz_index": next_idx,
                "user_answers": answers,
                "final_answer": f"Принято. Вопрос №{next_idx + 1}:\n{next_q}"
            }
        else:
            # Если вопросы закончились — меняем намерение на оценку
            return {
                **state,
                "user_answers": answers,
                "intent": "evaluate_quiz"
            }

    async def evaluate_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """Оценивает квиз, дает обратную связь и СБРАСЫВАЕТ состояние."""
        if session:
            await session.notify_ui(step="start_grade_exam", message="Проверяю ваши ответы...", tool="grade_exam")

        questions = state.get("quiz_questions", [])
        user_answers = state.get("user_answers", [])
        
        # Формируем отчет для инструмента проверки
        quiz_data = []
        for i, q_item in enumerate(questions):
            quiz_data.append({
                "question": q_item["q"],
                "correct_answer": q_item["a"],
                "user_answer": user_answers[i] if i < len(user_answers) else "Нет ответа"
            })

        # Инструмент проверки квиза
        evaluation_result = await grade_exam_async("quiz_session", quiz_data)
        
        # Используем LLM для формирования вежливой и подробной обратной связи (с поддержкой LaTeX)
        feedback_prompt = (
            "На основе результатов квиза составь развернутый отзыв для студента. "
            "Объясни ошибки, если они есть, и похвали за правильные ответы. "
            "Используй LaTeX для математических формул, если это уместно. "
            f"Результаты проверки: {evaluation_result}"
        )
        final_feedback = self.client.generate([feedback_prompt], temperature=0.3)[0]

        # Очищаем данные квиза, чтобы вернуть агент в "начальное состояние" для новых вопросов
        return {
            **state,
            "final_answer": final_feedback,
            "quiz_questions": [],
            "current_quiz_index": 0,
            "user_answers": [],
            "intent": "general"
        }

    # ---------- Вспомогательные методы ----------

    async def _parse_quiz_result(self, raw_text: str) -> List[Dict[str, str]]:
        """Превращает текст от инструмента генерации в список объектов через LLM."""
        prompt = (
            "Преобразуй этот текст квиза в строгий JSON список объектов с ключами 'q' (вопрос) и 'a' (правильный ответ). "
            "Верни ТОЛЬКО JSON.\n\n" + raw_text
        )
        res = self.client.generate([prompt], temperature=0)[0]
        try:
            return json.loads(res)
        except:
            # Запасной вариант парсинга, если LLM ошиблась в JSON
            self.log.error("Failed to parse quiz JSON")
            return [{"q": "Ошибка парсинга. Попробуйте еще раз.", "a": ""}]

    def _determine_intent(self, question: str) -> str:
        # Здесь должна быть логика из вашего исходного файла с PydanticModel
        # Для краткости предполагаем вызов оригинальной логики
        return "general" 

    # ---------- Сборка графа ----------

    def _build_graph(self):
        builder = StateGraph(AgentState)
        
        def wrap_node(node_func):
            async def wrapped_node(state: AgentState, config: Optional[Dict] = None):
                session = config["configurable"].get("session") if config else None
                return await node_func(state, session)
            return wrapped_node

        builder.add_node("planner", wrap_node(self.planner_node))
        builder.add_node("retrieve", wrap_node(self.retrieve_node))
        builder.add_node("direct_answer", wrap_node(self.direct_answer_node))
        builder.add_node("rag_answer", wrap_node(self.rag_answer_node))
        builder.add_node("create_quiz", wrap_node(self.create_quiz_node))
        builder.add_node("process_answer", wrap_node(self.process_quiz_answer_node))
        builder.add_node("evaluate_quiz", wrap_node(self.evaluate_quiz_node))

        builder.add_edge(START, "planner")

        # Роутинг после планировщика
        builder.add_conditional_edges(
            "planner",
            lambda s: s["intent"],
            {
                "general": "direct_answer",
                "rag_answer": "retrieve",
                "generate_quiz": "retrieve",
                "quiz_answering": "process_answer", # Переход к обработке текущего ответа
                "evaluate_quiz": "evaluate_quiz"
            }
        )

        builder.add_conditional_edges(
            "retrieve",
            lambda s: "create_quiz" if s["intent"] == "generate_quiz" else "rag_answer",
            {
                "create_quiz": "create_quiz",
                "rag_answer": "rag_answer"
            }
        )

        # После обработки ответа: либо завершаем ход (ждем ввода), либо идем на оценку
        builder.add_conditional_edges(
            "process_answer",
            lambda s: "evaluate_quiz" if s["intent"] == "evaluate_quiz" else END,
            {
                "evaluate_quiz": "evaluate_quiz",
                END: END
            }
        )

        builder.add_edge("direct_answer", END)
        builder.add_edge("rag_answer", END)
        builder.add_edge("create_quiz", END) # Завершаем ход после первого вопроса
        builder.add_edge("evaluate_quiz", END)

        return builder.compile(checkpointer=self.memory)

```

### Ключевые изменения:

1. **Цикл опроса**: Добавлен узел `process_answer` и соответствующее состояние `quiz_answering`. Агент больше не отдает всё сразу, а "засыпает" (`END`) после каждого вопроса, ожидая следующего сообщения от пользователя.
2. **Память состояний**: В `AgentState` добавлены `current_quiz_index` и `user_answers`. Благодаря `MemorySaver`, когда пользователь присылает ответ, агент "вспоминает", на каком вопросе он остановился.
3. **Умная проверка**: `evaluate_quiz_node` теперь собирает все вопросы и все ответы пользователя в единую структуру для инструмента `grade_exam_async`, а затем просит LLM объяснить результаты понятным языком.
4. **Сброс (Initial State)**: В конце узла `evaluate_quiz` поля квиза обнуляются. Это позволяет пользователю продолжить обычное общение с агентом или начать новый квиз без конфликтов состояний.


