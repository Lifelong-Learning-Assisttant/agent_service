from typing import Dict, Optional, TypedDict, Literal, List, Set, Any
import os
import asyncio
import json
import uuid
from datetime import datetime, timezone
from collections import deque

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from llm_service.llm_client import LLMClient
from settings import get_settings
from logger import get_logger
from langchain_tools import make_async_tools, rag_search_async, rag_generate_async, generate_exam_async, grade_exam_async, get_algo_problem_info, get_algo_solution
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
        Двухрежимный планировщик: Idle vs Quiz Active.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:planner | question_len=%d | session=%s", len(q), session is not None)
        t0 = time.perf_counter()

        # 1. Проверка CLI-команд (имеют высший приоритет в любом режиме)
        if q == "/finish_quizz":
            intent = "evaluate_quiz"
            self.log.info("CLI_CMD: /finish_quizz detected")
        elif q == "/skip_question":
            intent = "skip_question"
            self.log.info("CLI_CMD: /skip_question detected")
        else:
            # 2. Проверка режима (Квиз активен?)
            quiz_questions = state.get("quiz_questions", [])
            current_idx = state.get("current_quiz_index", 0)
            quiz_active = quiz_questions and len(quiz_questions) > 0 and current_idx < len(quiz_questions)

            if quiz_active:
                # Если пользователь явно отправил ответ через режим ANSWER_QUIZ
                # Или если мы находимся в режиме квиза и сообщение не похоже на команду/вопрос
                if state.get("interaction_mode") == "ANSWER_QUIZ":
                    intent = "quiz_answering"
                    self.log.info("Planner (QuizMode): explicit ANSWER_QUIZ detected")
                else:
                    # В режиме квиза (даже если AI_SYNC), мы сначала проверяем, не является ли это RAG вопросом.
                    # Но если интент-анализ сомневается, в режиме квиза приоритет у quiz_answering.
                    intent = self._determine_intent(q, mode="quiz_active")
                    
                    # Если LLM в режиме активного квиза вернула 'general' или 'rag_answer' для короткого сообщения,
                    # скорее всего это просто короткий ответ, который она не смогла классифицировать.
                    # Принудительно ставим quiz_answering, если это не явный вопрос (нет знака вопроса или спец. слов).
                    is_short = len(q.split()) < 15
                    has_question_mark = "?" in q
                    if (intent in ["general", "rag_answer"]) and is_short and not has_question_mark:
                        intent = "quiz_answering"
                        self.log.info("Planner (QuizMode): forced quiz_answering for short message in active quiz (intent was %s)", state.get("intent"))
                    
                    self.log.info("Planner (QuizMode): determined intent=%s", intent)
            else:
                # Обычный режим
                if session:
                    await session.notify_ui(
                        step="start_planner",
                        message="Анализ запроса и определение намерения",
                        tool="planner",
                        level="info"
                    )
                
                mode = "idle"
                if state.get("interaction_mode") == "ALGOS":
                    mode = "algos"
                
                intent = self._determine_intent(q, mode=mode)
                self.log.info(f"Planner ({mode} Mode): determined intent={intent}")

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="intent_determined",
                message=f"Намерение: {intent}",
                tool="planner",
                level="info",
                meta={"intent": intent}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:planner | intent=%s | %.1f ms", intent, dt)
        return {**state, "intent": intent}

    async def retrieve_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Ищет сырые документы в RAG.
        """
        import time
        import json

        q = (state.get("question") or "").strip()
        self.log.info("start:retrieve | q_len=%d", len(q))
        t0 = time.perf_counter()

        if session:
            await session.notify_ui(
                step="start_retrieval",
                message="Поиск в базе знаний Яндекса...",
                tool="rag_search",
                level="info"
            )

        # Вызываем только поиск (без генерации)
        search_result_json = await rag_search_async(q, top_k=5)
        
        docs = []
        try:
            data = json.loads(search_result_json)
            # RAG сервис возвращает SearchResponse с полем 'documents'
            if isinstance(data, dict) and "documents" in data:
                raw_docs = data["documents"]
                sources = data.get("sources", [])
                # Унифицируем формат
                for i, content in enumerate(raw_docs):
                    docs.append({
                        "content": content,
                        "source": sources[i] if i < len(sources) else "Учебник Яндекса",
                        "score": 1.0, # В будущем будем брать реальный score
                        "type": "handbook"
                    })
        except Exception as e:
            self.log.error("Failed to parse RAG search result: %s", e)

        if session:
            await session.notify_ui(
                step="retrieval_done",
                message=f"Найдено фрагментов: {len(docs)}",
                tool="rag_search",
                level="info",
                meta={"docs_count": len(docs)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:retrieve | docs_count=%d | %.1f ms", len(docs), dt)
        return {**state, "documents": docs}

    async def prepare_material_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Узел-редактор: синтезирует Golden Source Markdown из всех источников.
        """
        import time
        import os

        self.log.info("start:prepare_material")
        t0 = time.perf_counter()

        if session:
            await session.notify_ui(
                step="start_prepare_material",
                message="Синтез и проверка учебных материалов...",
                tool="prepare_material",
                level="info"
            )

        docs = state.get("documents", [])
        if not docs:
            self.log.warning("No documents found for material preparation")
            return {**state, "prepared_material": "", "is_relevant": False}

        # Формируем список чанков для LLM
        chunks_input = ""
        for i, doc in enumerate(docs):
            source_info = doc.get("source", "Unknown")
            if isinstance(source_info, dict):
                source_info = source_info.get("title") or source_info.get("url") or str(source_info)
            
            chunks_input += f"--- ФРАГМЕНТ {i+1} (Источник: {source_info}) ---\n{doc['content']}\n\n"

        # Загружаем промпт
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "prepare_quiz_material.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read().strip()

        final_prompt = template.format(chunks=chunks_input)

        # Извлекаем настройки из состояния (для RAG используем настройки rag)
        app_settings = state.get("app_settings")
        provider = None
        model = None
        if app_settings and "rag" in app_settings:
            provider = app_settings["rag"].get("provider")
            model = app_settings["rag"].get("model")

        # Вызываем LLM для синтеза (temperature=0 для стабильности)
        if provider:
            # Создаем временный клиент с нужным провайдером
            temp_client = LLMClient(provider=provider)
            chat = temp_client.create_chat(model=model, temperature=0)
        else:
            chat = self.client.create_chat(temperature=0)
            
        res = chat.invoke([HumanMessage(content=final_prompt)])
        golden_markdown = res.content

        # Ограничиваем размер материала для стабильности генератора тестов
        if len(golden_markdown) > 5000:
            self.log.warning(f"Material too long ({len(golden_markdown)}), truncating...")
            golden_markdown = golden_markdown[:5000] + "\n\n... [Материал обрезан из-за объема]"

        # Проверка релевантности (упрощенная: если LLM вернула слишком короткий текст или отказ)
        is_relevant = len(golden_markdown) > 50 and "не нашел" not in golden_markdown.lower()

        if session:
            await session.notify_ui(
                step="prepare_material_done",
                message="Материал подготовлен и структурирован",
                tool="prepare_material",
                level="info"
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:prepare_material | len=%d | relevant=%s | %.1f ms", len(golden_markdown), is_relevant, dt)
        
        return {**state, "prepared_material": golden_markdown, "is_relevant": is_relevant}

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
        # Извлекаем настройки из состояния (для прямого ответа используем настройки agent)
        app_settings = state.get("app_settings")
        provider = None
        model = None
        if app_settings and "agent" in app_settings:
            provider = app_settings["agent"].get("provider")
            model = app_settings["agent"].get("model")

        # Используем invoke для доступа к метаданным (reasoning)
        if provider:
            temp_client = LLMClient(provider=provider)
            chat = temp_client.create_chat(model=model, temperature=0.2)
        else:
            chat = self.client.create_chat(temperature=0.2)
            
        res = chat.invoke([HumanMessage(content=prompt)])
        answer = res.content
        
        # Извлекаем рассуждения (thought) для Z.ai
        thought = ""
        if hasattr(res, 'additional_kwargs'):
            thought = res.additional_kwargs.get('reasoning_content', '')
        
        if not thought and hasattr(res, 'response_metadata'):
            thought = res.response_metadata.get('thought', '')

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
        self.log.info("done:direct_answer | out_len=%d | thought_len=%d | %.1f ms", len(answer or ""), len(thought), dt)
        return {**state, "final_answer": answer, "thought": thought}

    async def rag_answer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Генерирует финальный ответ пользователю, используя подготовленный Markdown.
        """
        import time

        self.log.info("start:rag_answer")
        t0 = time.perf_counter()

        if not state.get("is_relevant"):
            answer = "К сожалению, в учебнике Яндекса не нашлось достаточно информации, чтобы точно ответить на этот вопрос. Попробуйте переформулировать запрос."
            return {**state, "final_answer": answer}

        if session:
            await session.notify_ui(
                step="start_rag_answer",
                message="Формирование ответа на основе материалов...",
                tool="rag_generate",
                level="info"
            )

        q = state.get("question", "")
        context = state.get("prepared_material", "")

        prompt = (
            f"Используя предоставленный ниже учебный материал, подробно ответь на вопрос пользователя.\n"
            f"Вопрос: {q}\n\n"
            f"МАТЕРИАЛ:\n{context}\n\n"
            f"Твой ответ должен быть структурированным, точным и сохранять все формулы."
        )

        # Извлекаем настройки из состояния (для RAG ответа)
        app_settings = state.get("app_settings")
        provider = None
        model = None
        if app_settings and "rag" in app_settings:
            provider = app_settings["rag"].get("provider")
            model = app_settings["rag"].get("model")

        if provider:
            temp_client = LLMClient(provider=provider)
            chat = temp_client.create_chat(model=model, temperature=0.2)
        else:
            chat = self.client.create_chat(temperature=0.2)
            
        res = chat.invoke([HumanMessage(content=prompt)])
        answer = res.content
        
        thought = ""
        if hasattr(res, 'additional_kwargs'):
            thought = res.additional_kwargs.get('reasoning_content', '')

        # Добавляем список источников из state["documents"]
        raw_sources = []
        for doc in state.get("documents", []):
            src = doc.get("source", "Учебник Яндекса")
            if isinstance(src, dict):
                src = src.get("title") or src.get("url") or str(src)
            raw_sources.append(str(src))
            
        sources = list(set(raw_sources))
        if sources:
            answer += "\n\n**Источники:**\n" + "\n".join([f"- {s}" for s in sources])

        # Если квиз активен, возвращаем контекст вопроса
        quiz_questions = state.get("quiz_questions", [])
        current_idx = state.get("current_quiz_index", 0)
        if quiz_questions and current_idx < len(quiz_questions):
            current_q = quiz_questions[current_idx]["q"]
            answer = (
                f"{answer}\n\n"
                f"--- [SYSTEM: QUIZ_CONTEXT_RESUMED] ---\n"
                f"**Напоминаю текущий вопрос квиза (№{current_idx + 1}):**\n"
                f"{current_q}"
            )

        if session:
            await session.notify_ui(
                step="rag_answer_done",
                message="Ответ сформирован",
                tool="rag_generate",
                level="info"
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:rag_answer | %.1f ms", dt)
        return {**state, "final_answer": answer, "thought": thought}

    async def create_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Генерирует квиз на основе подготовленного материала.
        """
        import time
        import json

        self.log.info("start:create_quiz")
        t0 = time.perf_counter()

        if session:
            await session.notify_ui(
                step="start_generate_exam",
                message="Генерация вопросов квиза...",
                tool="generate_exam",
                level="info"
            )

        context = state.get("prepared_material", "")
        if not context:
            context = "# Общий квиз по ML\n\n## Основы\nМашинное обучение — это..."

        # Попытка 1: Используем специализированный сервис генерации
        # Настраиваем конфигурацию из настроек приложения
        config = {
            "total_questions": getattr(self.cfg, "quiz_total_questions", 10),
            "single_choice_ratio": getattr(self.cfg, "quiz_single_choice_ratio", 0.4),
            "multiple_choice_ratio": getattr(self.cfg, "quiz_multiple_choice_ratio", 0.3),
            "open_ended_ratio": getattr(self.cfg, "quiz_open_ended_ratio", 0.3),
            "language": getattr(self.cfg, "quiz_language", "ru"),
            "difficulty": "medium"
        }
        self.log.info("Quiz config: %d questions, %s, ratio %s/%s/%s",
                      config["total_questions"], config["language"],
                      config["single_choice_ratio"], config["multiple_choice_ratio"], config["open_ended_ratio"])

        raw_quiz = await generate_exam_async(context, config=config)
        
        if "error" in raw_quiz:
            self.log.error(f"Test generator error: {raw_quiz}")

        questions = await self._parse_quiz_result(raw_quiz)
        
        # Если парсинг не удался, пробуем сгенерировать через LLM напрямую
        if not questions or len(questions) == 0 or "Ошибка" in questions[0].get("q", ""):
            if session:
                await session.notify_ui(
                    step="generate_retry",
                    message="Первый метод не сработал, генерирую вопросы напрямую через LLM...",
                    tool="generate_exam",
                    level="warn"
                )
            
            # Прямая генерация через LLM
            prompt = (
                f"Сгенерируй 3-5 вопросов по теме:\n{context}\n\n"
                "Формат: каждый вопрос на новой строке, после вопроса через | укажите правильный ответ.\n"
                "Пример:\n"
                "Что такое градиентный спуск?|Метод оптимизации\n"
                "Как работает нейронная сеть?|Через передачу сигналов\n\n"
                "Верни только вопросы и ответы в указанном формате."
            )
            
            raw_quiz = self.client.generate([prompt], temperature=0.3)[0]
            questions = await self._parse_quiz_result(raw_quiz)
            
            # Если и это не сработало, создаем заглушку
            if not questions or len(questions) == 0:
                questions = [
                    {"q": "Какой-то вопрос 1?", "a": "Ответ 1"},
                    {"q": "Какой-то вопрос 2?", "a": "Ответ 2"},
                    {"q": "Какой-то вопрос 3?", "a": "Ответ 3"}
                ]
        
        first_q = questions[0]["q"]

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="quizz_question",
                message=f"Начинаем квиз! Вопрос №1:\n{first_q}",
                tool="generate_exam",
                level="info",
                meta={
                    "final_answer": f"Начинаем квиз! Вопрос №1:\n{first_q}",
                    "current_quiz_index": 0,
                    "total_questions": len(questions)
                }
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:create_quiz | questions_count=%d | %.1f ms", len(questions), dt)
        
        return {
            **state,
            "quiz_questions": questions,
            "current_quiz_index": 0,
            "user_answers": [],
            "final_answer": f"[SYSTEM: QUIZ_STARTED] {first_q}" # Уникальный маркер для фильтрации
        }

    async def evaluate_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Оценивает квиз, дает обратную связь и СБРАСЫВАЕТ состояние.
        """
        import time
        import json

        self.log.info("start:evaluate_quiz")
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_grade_exam",
                message="Проверяю ваши ответы...",
                tool="grade_exam",
                level="info"
            )

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
        
        # Формируем детальный отчет для пользователя
        detailed_report = []
        correct_count = 0
        
        for i, q_item in enumerate(questions):
            question = q_item["q"]
            correct_answer = q_item["a"]
            user_answer = user_answers[i] if i < len(user_answers) else "Нет ответа"
            
            detailed_report.append(
                f"Вопрос {i+1}: {question}\n"
                f"Ваш ответ: {user_answer}\n"
                f"Правильный ответ: {correct_answer}\n"
            )
        
        # Используем LLM для формирования вежливой и подробной обратной связи
        summary_prompt = (
            f"На основе этого квиза составь развернутый отзыв для студента:\n\n"
            f"Всего вопросов: {len(questions)}\n"
            f"Результаты проверки: {evaluation_result}\n\n"
            f"Детальный разбор:\n"
            f"{'\n'.join(detailed_report)}\n\n"
            f"Дай рекомендации по улучшению и объясни правильные ответы."
        )
        final_feedback = self.client.generate([summary_prompt], temperature=0.3)[0]
        
        # Добавляем статистику в начало
        final_answer = (
            f"📊 **Результаты квиза**\n"
            f"Всего вопросов: {len(questions)}\n\n"
            f"{final_feedback}"
        )

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="grade_done",
                message="Оценка выполнена",
                tool="grade_exam",
                level="info",
                meta={"length": len(final_answer)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:evaluate_quiz | feedback_len=%d | %.1f ms", len(final_answer or ""), dt)
        
        # Очищаем данные квиза, чтобы вернуть агент в "начальное состояние"
        return {
            **state,
            "final_answer": final_answer,
            "quiz_questions": [],
            "current_quiz_index": 0,
            "user_answers": [],
            "intent": "general"
        }

    async def process_quiz_answer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Записывает ответ пользователя и выдает СЛЕДУЮЩИЙ вопрос или переходит к оценке.
        """
        import time

        self.log.info("start:process_quiz_answer")
        t0 = time.perf_counter()

        idx = state.get("current_quiz_index", 0)
        questions = state.get("quiz_questions", [])
        intent = state.get("intent")
        
        # Инициализируем answers как пустой список если None
        answers = state.get("user_answers")
        if answers is None:
            answers = []

        # 1. Сохраняем ответ пользователя на ТЕКУЩИЙ вопрос
        if intent == "skip_question":
            user_reply = "[SYSTEM: SKIPPED]"
        else:
            user_reply = state.get("question", "")
            
        answers.append(user_reply)

        # 2. Переходим к следующему индексу
        next_idx = idx + 1

        # Проверяем, есть ли следующий вопрос
        has_next_question = next_idx < len(questions)
        
        if has_next_question:
            # Если есть еще вопросы — задаем следующий
            next_q = questions[next_idx]["q"]
            
            # Уведомление
            if session:
                await session.notify_ui(
                    step="quizz_question",
                    message=f"Принято. Вопрос №{next_idx + 1}:\n{next_q}",
                    tool="process_answer",
                    level="info",
                    meta={
                        "final_answer": f"Принято. Вопрос №{next_idx + 1}:\n{next_q}",
                        "current_quiz_index": next_idx,
                        "total_questions": len(questions)
                    }
                )
            
            dt = (time.perf_counter() - t0) * 1000
            self.log.info("done:process_quiz_answer | next_idx=%d | %.1f ms", next_idx, dt)
            
            return {
                **state,
                "current_quiz_index": next_idx,
                "user_answers": answers,
                "final_answer": f"[SYSTEM: NEXT_QUESTION] {next_q}" # Уникальный маркер для фильтрации
            }
        else:
            # Если вопросы закончились — меняем намерение на оценку
            if session:
                await session.notify_ui(
                    step="quiz_complete",
                    message="Все вопросы пройдены, начинаю оценку...",
                    tool="process_answer",
                    level="info"
                )
            
            dt = (time.perf_counter() - t0) * 1000
            self.log.info("done:process_quiz_answer | quiz_complete | %.1f ms", dt)
            
            return {
                **state,
                "user_answers": answers,
                "intent": "evaluate_quiz"
            }

    async def algo_interviewer_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Узел интервьюера для AlgoLab. Анализирует код пользователя и дает подсказки.
        """
        import time
        from langchain_tools import get_algo_problem_info, get_algo_solution

        self.log.info("start:algo_interviewer")
        t0 = time.perf_counter()

        if session:
            await session.notify_ui(
                step="start_algo_help",
                message="Анализ вашего решения и подготовка подсказки...",
                tool="algo_interviewer",
                level="info"
            )

        problem_id = state.get("problem_id") or "valid_parentheses"
        user_code = state.get("user_code", "")
        question = state.get("question", "")

        # 1. Получаем инфо о задаче и эталонное решение
        problem_info_json = await get_algo_problem_info.ainvoke(problem_id)
        solution_info_json = await get_algo_solution.ainvoke(problem_id)
        
        problem_info = json.loads(problem_info_json)
        solution_info = json.loads(solution_info_json)

        # 2. Формируем промпт для интервьюера
        prompt = (
            f"Ты — опытный интервьюер в BigTech. Ты помогаешь студенту решить задачу в AlgoLab.\n"
            f"ЗАДАЧА: {problem_info.get('task_description', 'N/A')}\n"
            f"ЗАМЕТКИ ИНТЕРВЬЮЕРА: {problem_info.get('interviewer_notes', 'N/A')}\n"
            f"ЭТАЛОННОЕ РЕШЕНИЕ (ДЛЯ ТЕБЯ): {solution_info.get('solution', 'N/A')}\n\n"
            f"ТЕКУЩИЙ КОД ПОЛЬЗОВАТЕЛЯ:\n```python\n{user_code}\n```\n\n"
            f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}\n\n"
            f"ИНСТРУКЦИЯ: Дай наводящую подсказку или объясни ошибку. "
            f"НЕ ДАВАЙ ГОТОВЫЙ КОД. Будь кратким и поддерживающим. Используй KaTeX для формул."
        )

        chat = self.client.create_chat(temperature=0.4)
        res = chat.invoke([HumanMessage(content=prompt)])
        answer = res.content

        if session:
            await session.notify_ui(
                step="algo_help_done",
                message="Подсказка готова",
                tool="algo_interviewer",
                level="info"
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:algo_interviewer | %.1f ms", dt)
        return {**state, "final_answer": answer}

    async def _parse_quiz_result(self, raw_text: str) -> List[Dict[str, str]]:
        """
        Превращает ответ от test_generator API в список объектов {"q": "...", "a": "..."}.
        """
        import json
        
        # Парсим JSON ответ от API
        try:
            data = json.loads(raw_text)
            
            # Формат ответа test_generator: {"exam_id": "...", "questions": [...], "config_used": {...}}
            if isinstance(data, dict) and "questions" in data:
                questions = data["questions"]
                result = []
                
                for q in questions:
                    if isinstance(q, dict):
                        # Извлекаем вопрос и правильный ответ
                        stem = q.get("stem", "")
                        question_type = q.get("type", "")
                        correct_indices = q.get("correct", [])
                        options = q.get("options", [])
                        
                        if stem and question_type in ["single_choice", "multiple_choice"]:
                            # Формируем правильный ответ
                            if correct_indices and options:
                                # Для single_choice берем первый индекс
                                # Для multiple_choice объединяем все правильные варианты
                                correct_answers = [options[i] for i in correct_indices if i < len(options)]
                                correct_text = "; ".join(correct_answers)
                                result.append({"q": stem, "a": correct_text})
                            else:
                                # Если нет вариантов, просто сохраняем вопрос
                                result.append({"q": stem, "a": "См. материал"})
                        elif stem and question_type == "open_ended":
                            # Для open-ended берем reference_answer
                            ref_answer = q.get("reference_answer", "См. материал")
                            result.append({"q": stem, "a": ref_answer})
                
                if result:
                    return result
            
            # Альтернативный формат: список вопросов напрямую
            elif isinstance(data, list):
                result = []
                for q in data:
                    if isinstance(q, dict):
                        stem = q.get("stem", "")
                        correct = q.get("correct", [])
                        options = q.get("options", [])
                        
                        if stem:
                            if correct and options:
                                correct_answers = [options[i] for i in correct if i < len(options)]
                                result.append({"q": stem, "a": "; ".join(correct_answers)})
                            else:
                                result.append({"q": stem, "a": "См. материал"})
                
                if result:
                    return result
            
            # Если формат не распознан, используем LLM для парсинга
            self.log.warning(f"Unexpected format from test_generator, using LLM fallback")
            
        except Exception as e:
            self.log.error(f"Error parsing test_generator response: {e}")
        
        # Fallback: используем LLM для парсинга
        prompt = (
            "Преобразуй этот текст квиза в строгий JSON список объектов с ключами 'q' (вопрос) и 'a' (правильный ответ). "
            "Верни ТОЛЬКО чистый JSON без markdown разметки.\n\n" + raw_text
        )
        res = self.client.generate([prompt], temperature=0)[0]
        try:
            # Очищаем от возможных ```json ... ```
            cleaned_res = res.strip()
            if cleaned_res.startswith("```json"):
                cleaned_res = cleaned_res[7:]
            if cleaned_res.endswith("```"):
                cleaned_res = cleaned_res[:-3]
            return json.loads(cleaned_res.strip())
        except:
            self.log.error("Failed to parse quiz JSON even with LLM")
            return [{"q": "Ошибка парсинга. Попробуйте еще раз.", "a": ""}]

    # ---------- Ветвление ----------
    @staticmethod
    def route_after_planner(state: AgentState) -> str:
        """Решает, куда идти после планирования."""
        intent = state.get("intent", "general")
        if intent == "general":
            return "direct_answer"
        elif intent == "rag_answer":
            return "retrieve"
        elif intent == "generate_quiz":
            return "retrieve"
        elif intent == "quiz_answering" or intent == "skip_question":
            return "process_answer"
        elif intent == "evaluate_quiz":
            return "evaluate_quiz"
        elif intent == "algo_help":
            return "algo_interviewer"
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

    def _determine_intent(self, question: str, mode: str = "idle") -> str:
        """Определяет намерение пользователя в зависимости от режима."""
        from pydantic import BaseModel, Field
        from typing import Literal
        
        class IntentModel(BaseModel):
            intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering", "skip_question", "algo_help"] = Field(
                description="Намерение пользователя"
            )

        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "intent_determination.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            base_prompt = f.read().strip()

        # Добавляем контекст режима в промпт
        mode_context = f"\nТЕКУЩИЙ РЕЖИМ: {mode.upper()}\n"
        if mode == "quiz_active":
            mode_context += "ВНИМАНИЕ: Пользователь сейчас проходит тест. Любой обычный текст скорее всего является ответом на вопрос (quiz_answering)."
        elif mode == "algos":
            mode_context += "ВНИМАНИЕ: Пользователь сейчас решает алгоритмическую задачу в AlgoLab. Любой запрос о помощи или подсказке — это algo_help."
        
        parser = JsonOutputParser(pydantic_object=IntentModel)
        
        # Создаем шаблон промпта с инструкциями по форматированию
        prompt_template = PromptTemplate(
            template="{base_prompt}\n\n{format_instructions}",
            input_variables=["base_prompt"],
            partial_variables={"format_instructions": parser.get_format_instructions()}
        )
        
        # Формируем финальный промпт
        final_prompt = prompt_template.format(base_prompt=base_prompt.format(question=question) + mode_context)
        
        # Получаем чат-модель
        chat = self.client.create_chat(temperature=0.1)
        
        try:
            # Вызываем модель
            res = chat.invoke([HumanMessage(content=final_prompt)])
            
            # Парсим результат
            parsed_result = parser.parse(res.content)
            
            # Валидируем через Pydantic (хотя parser.parse уже возвращает dict, полезно убедиться в типах)
            intent_data = IntentModel(**parsed_result)
            return intent_data.intent
            
        except Exception as e:
            self.log.warning(f"Intent determination failed or parsing error: {e}. Fallback to 'general'.")
            # В случае любой ошибки (модель вернула мусор, невалидный JSON, или галлюцинации)
            # мы безопасно откатываемся к 'general', чтобы не ломать флоу пользователя.
            return "general"

    # ---------- Сборка графа ----------
    def _build_graph(self):
        """
        Собирает и компилирует граф.
        """
        self.log.debug("build_graph: begin")
        builder = StateGraph(AgentState)
        
        def wrap_node(node_func):
            async def wrapped_node(state: AgentState, config: Optional[Dict] = None):
                session = None
                if config and "configurable" in config:
                    session = config["configurable"].get("session")
                return await node_func(state, session)
            return wrapped_node
        
        builder.add_node("planner", wrap_node(self.planner_node))
        builder.add_node("retrieve", wrap_node(self.retrieve_node))
        builder.add_node("prepare_material", wrap_node(self.prepare_material_node))
        builder.add_node("direct_answer", wrap_node(self.direct_answer_node))
        builder.add_node("rag_answer", wrap_node(self.rag_answer_node))
        builder.add_node("create_quiz", wrap_node(self.create_quiz_node))
        builder.add_node("process_answer", wrap_node(self.process_quiz_answer_node))
        builder.add_node("evaluate_quiz", wrap_node(self.evaluate_quiz_node))
        builder.add_node("algo_interviewer", wrap_node(self.algo_interviewer_node))

        builder.add_edge(START, "planner")
        
        # 1. После Planner: либо прямой ответ, либо поиск, либо обработка квиза
        builder.add_conditional_edges(
            "planner",
            self.route_after_planner,
            {
                "direct_answer": "direct_answer",
                "retrieve": "retrieve",
                "process_answer": "process_answer",
                "evaluate_quiz": "evaluate_quiz",
                "algo_interviewer": "algo_interviewer"
            }
        )
        
        # 2. После поиска ВСЕГДА идем на подготовку материала (Golden Source)
        builder.add_edge("retrieve", "prepare_material")

        # 3. После подготовки решаем: дать ответ или создать квиз
        builder.add_conditional_edges(
            "prepare_material",
            self.route_after_retriever,
            {
                "rag_answer": "rag_answer",
                "create_quiz": "create_quiz"
            }
        )
        
        # 4. Процесс квиза
        builder.add_conditional_edges(
            "process_answer",
            lambda s: "evaluate_quiz" if s.get("intent") == "evaluate_quiz" else END,
            {
                "evaluate_quiz": "evaluate_quiz",
                END: END
            }
        )

        builder.add_edge("direct_answer", END)
        builder.add_edge("rag_answer", END)
        builder.add_edge("create_quiz", END)
        builder.add_edge("evaluate_quiz", END)
        builder.add_edge("algo_interviewer", END)

        app = builder.compile(checkpointer=self.memory)
        self.log.debug("build_graph: done")
        return app

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