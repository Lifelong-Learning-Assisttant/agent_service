from typing import Dict, Optional, TypedDict, Literal, List, Set, Any
import os
import asyncio
import json
import uuid
from datetime import datetime, timezone
from collections import deque

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from llm_service.llm_client import LLMClient
from settings import get_settings
from logger import get_logger
from tools import (
    rag_search_async,
    tavily_search_async,
    context7_docs_async,
    resolve_library_id_async,
    generate_exam_async,
    grade_exam_async,
    get_algo_problem_info,
    get_algo_solution
)
from graphs.supervisor import supervisor_graph
from agent_session import AgentSession


# ---------- Состояние графа ----------
class AgentState(TypedDict, total=False):
    """Общее состояние исполнения графа."""

    question: str
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering", "skip_question", "algo_help"]
    problem_id: str                 # ID текущей задачи (например, valid_parentheses)
    user_code: str                  # Текущий код пользователя
    documents: List[Dict[str, Any]] # Список унифицированных документов {content, source, score}
    prepared_material: str          # Синтезированный "Golden Source" в Markdown
    is_relevant: bool               # Флаг достаточности информации
    
    # Поля для интерактивного квиза
    quiz_questions: List[Dict[str, str]]  # Список {"question": "...", "answer": "..."}
    current_quiz_index: int               # Индекс текущего вопроса
    user_answers: List[str]               # Ответы пользователя
    
    final_answer: str
    thought: str                          # Рассуждения модели (reasoning)
    
    # Режимы и настройки
    interaction_mode: str                 # AI_SYNC | ANSWER_QUIZ | ALGOS
    mode: str                             # qa | quiz | algos
    app_settings: Any


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

        # Инициализируем инструменты (V3 использует прямые вызовы функций в узлах)
        self.tool_names = ["rag_search", "web_search", "docs_search", "generate_exam", "grade_exam", "get_algo_problem_info", "get_algo_solution"]
        self.log.info("V3 Modular architecture initialized with tools: %s", self.tool_names)

        # Инициализируем память для графа
        self.memory = MemorySaver()

        # Инициализируем хранилище сессий и семафор для ограничения параллелизма
        self.sessions: Dict[str, AgentSession] = {}
        concurrency_limit = getattr(self.cfg, 'concurrency_limit', 2)
        self._concurrency_sem = asyncio.Semaphore(concurrency_limit)
        self._sweeper_task: Optional[asyncio.Task] = None
        self._sweeper_started = False

        self.app = supervisor_graph

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

    # ПРИМЕЧАНИЕ: Все узлы графа вынесены в папку graphs/ для соблюдения модульности V3.
    # В этом классе оставлена только логика управления сессиями и запуска.


    # ---------- Публичный вызов ----------
    async def run(self, question: str, session_id: str = "default", settings: Optional[Any] = None, interaction_mode: Optional[str] = None) -> str:
        """
        Запускает обработку вопроса через AgentSession.
        Args:
            question: Вопрос пользователя.
            session_id: Идентификатор сессии.
            settings: Настройки моделей.
            interaction_mode: Режим взаимодействия.
        Returns:
            Финальный ответ строкой.
        """
        import time

        # Запускаем sweeper при первом вызове
        self._ensure_sweeper_started()

        self.log.info("run: start | session_id=%s | mode=%s | q_len=%d", session_id, interaction_mode, len(question or ""))
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
            await session.start(question, settings=settings, interaction_mode=interaction_mode)
            
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