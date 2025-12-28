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
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"]
    documents: List[str]
    
    # Поля для интерактивного квиза
    quiz_questions: List[Dict[str, str]]  # Список {"question": "...", "answer": "..."}
    current_quiz_index: int               # Индекс текущего вопроса
    user_answers: List[str]               # Ответы пользователя
    
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
        Определяет, продолжаем ли мы квиз или анализируем новый запрос.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:planner | question_len=%d | session=%s", len(q), session is not None)
        t0 = time.perf_counter()

        # Если квиз уже начат, принудительно идем по пути ответов
        quiz_active = state.get("quiz_questions") is not None and len(state.get("quiz_questions", [])) > 0
        current_idx = state.get("current_quiz_index", 0)
        
        if quiz_active and current_idx < len(state.get("quiz_questions", [])):
            intent = "quiz_answering"
        else:
            intent = self._determine_intent(q)

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_planner",
                message="Анализ запроса и определение намерения",
                tool="planner",
                level="info"
            )

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
        import os

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
                raw_answer = f"Ошибка RAG: {result_data['error']}"
            elif isinstance(result_data, dict) and "answer" in result_data:
                raw_answer = result_data["answer"]
            else:
                raw_answer = str(result_data)
        except:
            raw_answer = "Ошибка при обработке ответа от RAG сервиса"

        # Логируем полученный ответ для отладки
        self.log.info("RAG raw answer: %s", raw_answer[:200] + "..." if len(raw_answer) > 200 else raw_answer)

        # Уведомление о переформатировании
        if session:
            await session.notify_ui(
                step="start_reformatting",
                message="Переформатирование ответа с правильными формулами",
                tool="llm_reformat",
                level="info"
            )

        # Загружаем промпт для переформатирования
        reformat_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "reformat_latex.txt")
        with open(reformat_prompt_path, "r", encoding="utf-8") as f:
            reformat_prompt_template = f.read().strip()
        
        # Формируем промпт для LLM
        reformat_prompt = reformat_prompt_template + "\n\n" + raw_answer
        
        # Используем LLM для переформатирования
        answer = self.client.generate([reformat_prompt], temperature=0.1)[0]
        
        # Логируем результат переформатирования
        self.log.info("Reformatted answer: %s", answer[:200] + "..." if len(answer) > 200 else answer)

        # Уведомление об успехе
        if session:
            await session.notify_ui(
                step="rag_answer_done",
                message="Ответ на основе RAG сгенерирован и отформатирован",
                tool="rag_generate",
                level="info",
                meta={"length": len(answer)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:rag_answer | out_len=%d | %.1f ms", len(answer or ""), dt)
        return {**state, "final_answer": answer}

    async def create_quiz_node(self, state: AgentState, session: Optional["AgentSession"] = None) -> AgentState:
        """
        Генерирует квиз и задает ПЕРВЫЙ вопрос.
        """
        import time
        import json

        q = (state.get("question") or "").strip()
        self.log.info("start:create_quiz | q_len=%d", len(q))
        t0 = time.perf_counter()

        # Уведомление о начале
        if session:
            await session.notify_ui(
                step="start_generate_exam",
                message="Генерирую вопросы по материалам...",
                tool="generate_exam",
                level="info"
            )

        # Получаем документы и преобразуем в строку
        docs = state.get("documents", [])
        if isinstance(docs, list) and len(docs) > 0:
            # Если документы - это список словарей, извлекаем текст
            if isinstance(docs[0], dict):
                context = "\n".join([doc.get("content", "") for doc in docs if isinstance(doc, dict)])
            else:
                context = "\n".join([str(doc) for doc in docs])
        else:
            context = ""
        
        # Если нет контекста, создаем заглушку
        if not context:
            context = "Квиз по машинному обучени и глубокому обучению"
        
        # Попытка 1: Инструмент выдает вопросы и ответов
        raw_quiz = await generate_exam_async(context)
        
        # Парсим результат инструмента в структурированный список
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
                step="generate_done",
                message="Квиз сгенерирован",
                tool="generate_exam",
                level="info",
                meta={"length": len(questions)}
            )

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:create_quiz | questions_count=%d | %.1f ms", len(questions), dt)
        
        return {
            **state,
            "quiz_questions": questions,
            "current_quiz_index": 0,
            "user_answers": [],
            "final_answer": f"Начинаем квиз! Вопрос №1:\n{first_q}"
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
        
        # Инициализируем answers как пустой список если None
        answers = state.get("user_answers")
        if answers is None:
            answers = []

        # 1. Сохраняем ответ пользователя на ТЕКУЩИЙ вопрос
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
                    step="next_question",
                    message=f"Принято. Вопрос №{next_idx + 1}",
                    tool="process_answer",
                    level="info"
                )
            
            dt = (time.perf_counter() - t0) * 1000
            self.log.info("done:process_quiz_answer | next_idx=%d | %.1f ms", next_idx, dt)
            
            return {
                **state,
                "current_quiz_index": next_idx,
                "user_answers": answers,
                "final_answer": f"Принято. Вопрос №{next_idx + 1}:\n{next_q}"
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
            "Верни ТОЛЬКО JSON.\n\n" + raw_text
        )
        res = self.client.generate([prompt], temperature=0)[0]
        try:
            return json.loads(res)
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
        elif intent == "quiz_answering":
            return "process_answer"
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

    def _determine_intent(self, question: str) -> Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"]:
        """Определяет намерение пользователя с использованием LLM через PydanticOutputParser для гарантированного вывода."""
        from pydantic import BaseModel, Field
        from langchain_core.messages import HumanMessage
        from typing import Literal
        import os
        
        # Определяем Pydantic модель для структурированного вывода
        class IntentModel(BaseModel):
            """Модель намерения пользователя."""
            intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"] = Field(
                description="Намерение пользователя: general для общих вопросов, rag_answer для ответов из учебника, generate_quiz для создания квиза, evaluate_quiz для оценки результатов, quiz_answering для ответов на вопросы квиза"
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
        builder.add_node("process_answer", wrap_node(self.process_quiz_answer_node))
        builder.add_node("evaluate_quiz", wrap_node(self.evaluate_quiz_node))

        builder.add_edge(START, "planner")
        
        # Переходы после планировщика
        builder.add_conditional_edges(
            "planner",
            self.route_after_planner,
            {
                "direct_answer": "direct_answer",
                "retrieve": "retrieve",
                "process_answer": "process_answer",
                "evaluate_quiz": "evaluate_quiz"
            }
        )
        
        # Переходы после retrieve
        builder.add_conditional_edges(
            "retrieve",
            self.route_after_retriever,
            {
                "rag_answer": "rag_answer",
                "create_quiz": "create_quiz"
            }
        )
        
        # Переходы после обработки ответа: либо к следующему вопросу (END и ждем ввода),
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