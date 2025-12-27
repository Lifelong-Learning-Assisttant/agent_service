from typing import Dict, Optional, TypedDict, Literal, List, Set
import os
import asyncio
import uuid
from datetime import datetime, timezone
from collections import deque

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage

from llm_service.llm_client import LLMClient
from settings import get_settings
from logger import get_logger
from langchain_tools import make_async_tools, rag_search_async, rag_generate_async, generate_exam_async, grade_exam_async
from agent_session import AgentSession


# ---------- Состояние графа ----------
class AgentState(TypedDict, total=False):
    """Общее состояние исполнения графа."""

    question: str
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz"]
    documents: List[str]
    quiz_content: Optional[str]
    user_solution: Optional[str]
    final_answer: str


# ---------- Агентная система ----------
class AgentSystem:
    """
    Агент на LangGraph с роутингом:
    - router → определяет маршрут 'direct' | 'tools'
    - answer_direct → отвечает напрямую через LLM
    - answer_with_tools → использует доступные инструменты для ответа
    """

    def __init__(self, provider: Optional[str] = None) -> None:
        """
        Args:
            provider: Провайдер LLM ('openai' | 'openrouter' | 'mistral').
                      Если None — берётся из настроек.
        """
        self.log = get_logger(__name__)
        cfg = get_settings()
        # Используем провайдер по умолчанию, если не указан
        prov = provider or cfg.default_provider
        
        # Загружаем системный промпт
        system_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
        system_prompt = ""
        if os.path.exists(system_prompt_path):
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip()
        
        self.client = LLMClient(provider=prov, system_prompt=system_prompt)
        self.cfg = cfg
        self.log.info("Инициализация агента: provider=%s", prov)

        # Инициализируем инструменты
        self.tools = make_async_tools()
        self.tool_names = [tool.name for tool in self.tools]
        self.log.info("Available tools: %s", self.tool_names)

        # Инициализируем память для графа
        self.memory = MemorySaver()

        # Инициализируем хранилище сессий и семафор для ограничения параллелизма
        self.sessions: Dict[str, AgentSession] = {}
        concurrency_limit = getattr(self.cfg, 'concurrency_limit', 2)
        self._concurrency_sem = asyncio.Semaphore(concurrency_limit)
        self._sweeper_task: Optional[asyncio.Task] = None
        self._sweeper_started = False

        self.app = self._build_graph()

    # ---------- Управление сессиями ----------
    def create_session(self, session_id: str) -> AgentSession:
        """
        Создает и регистрирует новую сессию.
        
        Args:
            session_id: Идентификатор сессии
            
        Returns:
            Созданный AgentSession
        """
        if session_id in self.sessions:
            self.log.warning(f"Session {session_id} already exists, returning existing")
            return self.sessions[session_id]
        
        session = AgentSession(session_id, self)
        self.sessions[session_id] = session
        self.log.info(f"Created session {session_id}, total sessions: {len(self.sessions)}")
        return session
    
    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """
        Получает сессию по ID.
        
        Args:
            session_id: Идентификатор сессии
            
        Returns:
            AgentSession или None если не найдена
        """
        return self.sessions.get(session_id)
    
    def remove_session(self, session_id: str) -> None:
        """
        Удаляет сессию и освобождает ресурсы.
        
        Args:
            session_id: Идентификатор сессии
        """
        session = self.sessions.pop(session_id, None)
        if session:
            # Запускаем cleanup асинхронно через asyncio.create_task
            # Но для синхронного метода делаем await в фоне
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(session.cleanup())
                else:
                    loop.run_until_complete(session.cleanup())
            except RuntimeError:
                # Если нет event loop, просто игнорируем
                pass
            self.log.info(f"Removed session {session_id}, remaining: {len(self.sessions)}")
    
    def _ensure_sweeper_started(self) -> None:
        """Запускает фоновый sweeper для удаления старых сессий (только если еще не запущен)."""
        if not self._sweeper_started:
            try:
                loop = asyncio.get_running_loop()
                if self._sweeper_task is None or self._sweeper_task.done():
                    self._sweeper_task = asyncio.create_task(self._sweep_expired_sessions_loop())
                    self._sweeper_started = True
                    self.log.info("Started session sweeper")
            except RuntimeError:
                # Нет активного event loop, пропускаем запуск
                pass
    
    async def _sweep_expired_sessions_loop(self) -> None:
        """Фоновая задача: периодическая очистка старых сессий."""
        ttl_seconds = getattr(self.cfg, 'session_ttl_seconds', 600)
        
        while True:
            try:
                await asyncio.sleep(30)  # Проверка каждые 30 секунд
                await self.sweep_expired_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.error(f"Error in sweeper loop: {e}")
    
    async def sweep_expired_sessions(self) -> None:
        """
        Удаляет сессии, которые неактивны дольше TTL.
        Вызывается периодически sweeper-ом.
        """
        ttl_seconds = getattr(self.cfg, 'session_ttl_seconds', 600)
        now = datetime.now(timezone.utc)
        expired = []
        
        for session_id, session in self.sessions.items():
            age = (now - session.last_active_at).total_seconds()
            if age > ttl_seconds:
                expired.append(session_id)
        
        for session_id in expired:
            session = self.sessions.get(session_id)
            if session:
                await session.cleanup()
                del self.sessions[session_id]
                self.log.info(f"Evicted expired session {session_id} (age: {ttl_seconds}s)")
        
        if expired:
            self.log.info(f"Sweeper cleaned {len(expired)} sessions, remaining: {len(self.sessions)}")

    # ---------- Узлы графа ----------
    async def planner_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Анализирует запрос и определяет план действий (intent).
        Отправляет уведомления в UI.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:planner | question_len=%d | session=%s", len(q), session is not None)
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_planner",
                message="Анализ запроса и определение намерения",
                tool="planner",
                level="info"
            )
        else:
            self.log.warning("planner_node: session is None!")

        # Определяем намерение на основе запроса
        intent = self._determine_intent(q)

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="intent_determined",
                message=f"Определено намерение: {intent}",
                tool="planner",
                level="info",
                meta={"intent": intent}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:planner | intent=%s | %.1f ms", intent, dt)
        return {**state, "intent": intent}

    async def retrieve_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Ищет документы в RAG.
        Отправляет уведомления в UI.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:retrieve | q_len=%d", len(q))
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_retrieval",
                message="Поиск документов в RAG",
                tool="rag_search",
                level="info"
            )

        result = await rag_search_async(q)
        
        # Парсим JSON результат
        try:
            import json
            docs_data = json.loads(result)
            if isinstance(docs_data, dict) and "error" in docs_data:
                docs = []
            else:
                docs = docs_data if isinstance(docs_data, list) else [docs_data]
        except:
            docs = []

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="retrieval_done",
                message=f"Найдено документов: {len(docs)}",
                tool="rag_search",
                level="info",
                meta={"docs_count": len(docs)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:retrieve | docs_count=%d | %.1f ms", len(docs), dt)
        return {**state, "documents": docs}

    async def direct_answer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Отвечает без инструментов (болтовня).
        Отправляет уведомления в UI.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:direct_answer | q_len=%d", len(q))
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_direct_answer",
                message="Генерация прямого ответа",
                tool="direct_answer",
                level="info"
            )

        prompt = (
            "Ответь кратко и по делу, оформи в 1–2 абзаца; при необходимости добавь список.\n\n"
            f"Вопрос: {q}"
        )
        answer = self.client.generate([prompt], temperature=0.2)[0]

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="direct_answer_done",
                message="Прямой ответ сгенерирован",
                tool="direct_answer",
                level="info",
                meta={"length": len(answer)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:direct_answer | out_len=%d | %.1f ms", len(answer or ""), dt)
        return {**state, "final_answer": answer}

    async def rag_answer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Генерирует ответ на основе документов через RAG сервис.
        Отправляет уведомления в UI.
        """
        import time
        import json

        q = (state.get("question") or "").strip()
        self.log.info("start:rag_answer | q_len=%d", len(q))
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_rag_answer",
                message="Генерация ответа на основе найденных документов",
                tool="rag_generate",
                level="info"
            )

        # Используем RAG сервис для генерации ответа
        result = await rag_generate_async(q)
        
        # Парсим JSON результат
        try:
            result_data = json.loads(result)
            if isinstance(result_data, dict) and "error" in result_data:
                answer = f"Ошибка RAG: {result_data['error']}"
            elif isinstance(result_data, dict) and "answer" in result_data:
                answer = result_data["answer"]
            else:
                answer = str(result_data)
        except:
            answer = "Ошибка при обработке ответа от RAG сервиса"

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="rag_answer_done",
                message="Ответ на основе RAG сгенерирован",
                tool="rag_generate",
                level="info",
                meta={"length": len(answer)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:rag_answer | out_len=%d | %.1f ms", len(answer or ""), dt)
        return {**state, "final_answer": answer}

    async def create_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Создает квиз на основе документов.
        Отправляет уведомления в UI.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:create_quiz | q_len=%d", len(q))
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_generate_exam",
                message="Генерация квиза на основе документов",
                tool="generate_exam",
                level="info"
            )

        context = "\n".join(state.get("documents", []))
        # Используем async-инструмент для генерации квиза
        from langchain_tools import generate_exam_async
        quiz = await generate_exam_async(context)

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="generate_done",
                message="Квиз сгенерирован",
                tool="generate_exam",
                level="info",
                meta={"length": len(quiz)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:create_quiz | quiz_len=%d | %.1f ms", len(quiz or ""), dt)
        return {**state, "quiz_content": quiz, "final_answer": quiz}

    async def evaluate_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Оценивает решение пользователя.
        Отправляет уведомления в UI.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:evaluate_quiz | q_len=%d", len(q))
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_grade_exam",
                message="Оценка ответов пользователя",
                tool="grade_exam",
                level="info"
            )

        # Получаем квиз и ответ пользователя
        quiz_content = state.get("quiz_content", "")
        user_solution = q

        # Оцениваем ответ через async-инструмент
        from langchain_tools import grade_exam_async
        feedback = await grade_exam_async("quiz_1", [{"solution": user_solution}])

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="grade_done",
                message="Оценка выполнена",
                tool="grade_exam",
                level="info",
                meta={"length": len(feedback)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:evaluate_quiz | feedback_len=%d | %.1f ms", len(feedback or ""), dt)
        return {**state, "final_answer": feedback}

    # ---------- Ветвление ----------
    @staticmethod
    def route_after_planner(state: AgentState) -> str:
        """Решает, куда идти после планирования."""
        intent = state.get("intent", "general")
        if intent == "general":
            return "direct_answer"
        elif intent == "evaluate_quiz":
            return "evaluate_quiz"
        else:
            return "retrieve"

    @staticmethod
    def route_after_retriever(state: AgentState) -> str:
        """Решает, что делать с полученными данными."""
        intent = state.get("intent", "general")
        if intent == "generate_quiz":
            return "create_quiz"
        else:
            return "rag_answer"

    def _determine_intent(self, question: str) -> Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz"]:
        """Определяет намерение пользователя с использованием LLM через PydanticOutputParser для гарантированного вывода."""
        from pydantic import BaseModel, Field
        from langchain_core.messages import HumanMessage
        from typing import Literal
        import os
        
        # Определяем Pydantic модель для структурированного вывода
        class IntentModel(BaseModel):
            """Модель намерения пользователя."""
            intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz"] = Field(
                description="Намерение пользователя: general для общих вопросов, rag_answer для ответов из учебника, generate_quiz для создания квиза, evaluate_quiz для оценки результатов"
            )
        
        # Загружаем промпт из файла
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "intent_determination.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                base_prompt = f.read().strip()
        else:
            # Если файл не найден, используем промпт по умолчанию
            base_prompt = (
                "Определи намерение пользователя. Возможные варианты:\n"
                "1. rag_answer - если пользователь задает вопрос по машинному обучению, глубокому обучению, нейронным сетям, ML, DL, AI, или упоминает учебник Яндекса.\n"
                "2. generate_quiz - если пользователь хочет пройти квиз, тест, викторину.\n"
                "3. evaluate_quiz - если пользователь хочет оценить результаты прохождения квиза. Результаты прохождения берем из памяти\n"
                "4. general - если пользователь хочет просто поговорить, задать общий вопрос, или поболтать без конкретной темы или все остальное что не относится к первым трем.\n\n"
                "Вопрос: {question}\n\n"
                "Выбери наиболее подходящий вариант: general, rag_answer, generate_quiz или evaluate_quiz."
            )
        
        # Форматируем промпт с вопросом
        prompt = base_prompt.format(question=question)
        
        # Добавляем инструкцию для структурированного вывода
        prompt += "\n\nВерни только JSON с полем intent."
        
        # Получаем чат-модель со структурированным выводом
        chat = self.client.create_chat(temperature=0.1)
        structured_chat = chat.with_structured_output(IntentModel)
        
        try:
            # Вызываем модель
            result = structured_chat.invoke([HumanMessage(content=prompt)])
            
            # Возвращаем intent (result - это словарь)
            return result.get("intent", "general")
        except Exception as e:
            self.log.error(f"Error in structured intent determination: {e}")
            # В случае ошибки возвращаем general по умолчанию
            return "general"

    # ---------- Сборка графа ----------
    def _build_graph(self):
        """
        Собирает и компилирует граф.
        Returns:
            Скомпилированный граф (Runnable).
        """
        self.log.debug("build_graph: begin")
        builder = StateGraph(AgentState)
        
        # Оборачиваем узлы для поддержки session из config
        def wrap_node(node_func):
            """Оборачивает узел для поддержки session из конфигурации."""
            async def wrapped_node(state: AgentState, config: Optional[Dict] = None):
                session = None
                if config and "configurable" in config:
                    session = config["configurable"].get("session")
                self.log.debug(f"wrap_node: {node_func.__name__}, session={session is not None}")
                return await node_func(state, session)
            return wrapped_node
        
        builder.add_node("planner", wrap_node(self.planner_node))
        builder.add_node("retrieve", wrap_node(self.retrieve_node))
        builder.add_node("direct_answer", wrap_node(self.direct_answer_node))
        builder.add_node("rag_answer", wrap_node(self.rag_answer_node))
        builder.add_node("create_quiz", wrap_node(self.create_quiz_node))
        builder.add_node("evaluate_quiz", wrap_node(self.evaluate_quiz_node))

        builder.add_edge(START, "planner")
        builder.add_conditional_edges(
            "planner",
            self.route_after_planner,
            {
                "direct_answer": "direct_answer",
                "retrieve": "retrieve",
                "evaluate_quiz": "evaluate_quiz"
            }
        )
        builder.add_conditional_edges(
            "retrieve",
            self.route_after_retriever,
            {
                "rag_answer": "rag_answer",
                "create_quiz": "create_quiz"
            }
        )
        builder.add_edge("direct_answer", END)
        builder.add_edge("rag_answer", END)
        builder.add_edge("create_quiz", END)
        builder.add_edge("evaluate_quiz", END)

        app = builder.compile(checkpointer=self.memory)
        self.log.debug("build_graph: done")
        return app

    # ---------- Публичный вызов ----------
    async def run(self, question: str, session_id: str = "default") -> str:
        """
        Запускает обработку вопроса через AgentSession.
        Args:
            question: Вопрос пользователя.
            session_id: Идентификатор сессии.
        Returns:
            Финальный ответ строкой.
        """
        import time

        # Запускаем sweeper при первом вызове
        self._ensure_sweeper_started()

        self.log.info("run: start | session_id=%s | q_len=%d", session_id, len(question or ""))
        t0 = time.perf_counter()
        
        # Получаем или создаем сессию
        session = self.get_session(session_id)
        if not session:
            session = self.create_session(session_id)
        
        # Проверяем, не выполняется ли уже сессия
        if session.is_running():
            self.log.warning(f"Session {session_id} is already running")
            return "Session is busy, please wait or use a different session_id"
        
        # Ограничиваем параллелизм
        async with self._concurrency_sem:
            # Запускаем сессию
            await session.start(question)
            
            # Ждем завершения
            if session.task:
                try:
                    await session.task
                except asyncio.CancelledError:
                    pass
        
        dt = (time.perf_counter() - t0) * 1000
        
        # Получаем финальный ответ из state
        final_answer = session.state.get("final_answer", "Ошибка: финальный ответ не сформирован")
        self.log.info("run: done  | session_id=%s | out_len=%d | %.1f ms", session_id, len(final_answer or ""), dt)
        
        # Возвращаем ответ (для совместимости с существующим API)
        return final_answer
    
    async def run_async(self, question: str, session_id: str = "default") -> asyncio.Task:
        """
        Асинхронный запуск обработки вопроса.
        Args:
            question: Вопрос пользователя.
            session_id: Идентификатор сессии.
        Returns:
            Task объект для ожидания результата.
        """
        # Запускаем sweeper при первом вызове
        self._ensure_sweeper_started()
        
        session = self.get_session(session_id)
        if not session:
            session = self.create_session(session_id)
        
        if session.is_running():
            self.log.warning(f"Session {session_id} is already running")
            return session.task
        
        async with self._concurrency_sem:
            await session.start(question)
            return session.task
