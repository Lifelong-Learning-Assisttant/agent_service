"""
Модуль содержит класс AgentSession для управления состоянием отдельной сессии агента.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from collections import deque
from typing import Optional, Dict, Any, TYPE_CHECKING
import httpx

from settings import get_settings
from logger import get_logger

if TYPE_CHECKING:
    from agent_system import AgentSystem, AgentState


class AgentSession:
    """
    Класс, инкапсулирующий состояние и задачи одной сессии агента.
    
    Поля:
    - session_id: str - идентификатор сессии
    - state: AgentState - текущее состояние агента
    - task: Optional[asyncio.Task] - текущая выполняющаяся задача
    - last_active_at: datetime - время последней активности
    - created_at: datetime - время создания сессии
    - last_events: deque - последние progress-события (maxlen=200)
    - lock: asyncio.Lock - лок для защиты state
    - cancelled: bool - флаг отмены
    - parent: AgentSystem - ссылка на родительскую систему
    """
    
    def __init__(self, session_id: str, parent: "AgentSystem", initial_state: Optional["AgentState"] = None, **opts):
        """
        Инициализация сессии.
        
        Args:
            session_id: Уникальный идентификатор сессии
            parent: Ссылка на AgentSystem для доступа к notify_ui и другим методам
            initial_state: Начальное состояние (опционально)
            **opts: Дополнительные параметры конфигурации
        """
        self.session_id = session_id
        self.parent = parent
        self.log = get_logger(__name__)
        self.cfg = get_settings()
        
        # Состояние сессии
        self.state: "AgentState" = initial_state or {}
        self.task: Optional[asyncio.Task] = None
        self.cancelled: bool = False
        
        # Временные метки
        self.created_at = datetime.now(timezone.utc)
        self.last_active_at = self.created_at
        
        # История событий
        self.last_events = deque(maxlen=200)
        
        # Лок для защиты state
        self.lock = asyncio.Lock()
        
        # Дополнительные параметры
        self.opts = opts
        
        self.log.info(f"AgentSession created: {session_id}")
    
    async def start(self, question: str) -> None:
        """
        Запускает обработку вопроса в фоновой задаче.
        
        Args:
            question: Вопрос пользователя
        """
        async with self.lock:
            if self.is_running():
                self.log.warning(f"Session {self.session_id} is already running")
                return
            
            # Обновляем состояние
            self.state["question"] = question
            self.touch()
            self.cancelled = False
            
            # Запускаем фоновую задачу
            self.task = asyncio.create_task(self._run_graph(question))
            self.log.info(f"Session {self.session_id} started task")
    
    async def _run_graph(self, question: str) -> None:
        """
        Внутренний метод: выполнение графа агента через LangGraph.
        Использует узлы из AgentSystem с интегрированными уведомлениями.
        
        Args:
            question: Вопрос пользователя
        """
        try:
            self.log.info(f"Session {self.session_id} running graph for question: {question[:50]}...")
            
            # Уведомление о начале выполнения
            await self.notify_ui(
                step="start_run",
                message="Начало обработки запроса",
                tool="agent",
                level="info",
                meta={"question": question}
            )
            
            # Получаем родительский AgentSystem
            if not hasattr(self.parent, 'app'):
                raise RuntimeError("Parent AgentSystem не имеет LangGraph app")
            
            # Обновляем состояние сессии
            async with self.lock:
                self.state["question"] = question
            
            # Подготавливаем конфиг для LangGraph с нашей сессией
            # LangGraph будет передавать session в каждый узел
            config = {
                "configurable": {
                    "thread_id": self.session_id,
                    "session": self  # Передаем сессию для доступа к notify_ui
                }
            }
            
            # Запускаем LangGraph с обновленным состоянием
            # Используем ainvoke для асинхронного выполнения
            final_state = await self.parent.app.ainvoke(
                self.state,
                config=config
            )
            
            # Сохраняем результат
            async with self.lock:
                self.state.update(final_state)
            
            # Уведомление о завершении
            final_answer = self.state.get("final_answer", "")
            await self.notify_ui(
                step="final_answer",
                message="Задача завершена",
                tool="agent",
                level="info",
                meta={"final_length": len(final_answer)}
            )
            
            self.log.info(f"Session {self.session_id} completed successfully")
            
        except asyncio.CancelledError:
            self.log.info(f"Session {self.session_id} was cancelled")
            await self.notify_ui(
                step="cancelled",
                message="Пользователь отменил выполнение",
                tool="agent",
                level="warn"
            )
        except Exception as e:
            self.log.error(f"Session {self.session_id} error: {e}")
            await self.notify_ui(
                step="tool_error",
                message=f"Ошибка выполнения: {str(e)}",
                tool="agent",
                level="error",
                meta={"error": str(e)}
            )
        finally:
            self.touch()
    
    async def notify_ui(self, step: str, message: str, tool: Optional[str] = None,
                       level: str = "info", meta: Optional[Dict[str, Any]] = None) -> None:
        """
        Отправляет progress-событие в Web UI.
        
        Args:
            step: Тип шага (start_run, intent_determined и т.д.)
            message: Сообщение для пользователя
            tool: Инструмент, который выполняется
            level: Уровень важности (info, warn, error)
            meta: Дополнительная метаинформация
        """
        # Формируем событие
        event = {
            "event_id": str(uuid.uuid4()),
            "session_id": self.session_id,
            "step": step,
            "tool": tool,
            "message": message,
            "level": level,
            "ts": datetime.now(timezone.utc).isoformat(),
            "meta": meta or {}
        }
        
        # Сохраняем в локальную историю
        async with self.lock:
            self.last_events.append(event)
            self.touch()
        
        self.log.info(f"notify_ui: step={step}, session={self.session_id}, msg={message[:50]}...")
        
        # Отправляем в Web UI (fire-and-forget)
        try:
            web_ui_url = self.cfg.web_ui_url
            if not web_ui_url:
                self.log.warning(f"Web UI URL not configured, skipping notification for session {self.session_id}")
                return
            
            url = f"{web_ui_url}/api/agent/progress"
            
            async with httpx.AsyncClient(timeout=1.0) as client:
                response = await client.post(url, json=event)
                self.log.info(f"notify_ui: sent to {url}, status={response.status_code}")
        except Exception as e:
            # Fire-and-forget: логируем, но не поднимаем исключение
            self.log.warning(f"Failed to notify UI for session {self.session_id}: {e}")
            # Можно сохранить событие в буфер для повторной отправки, но для demo не обязательно
    
    async def cancel(self) -> None:
        """Отменяет текущую задачу сессии."""
        async with self.lock:
            self.cancelled = True
            if self.task and not self.task.done():
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
                self.log.info(f"Session {self.session_id} cancelled")
    
    async def save_state(self) -> None:
        """Хук для сохранения состояния (для demo - заглушка)."""
        # Для demo: можно сохранять в файл или Redis
        pass
    
    async def load_state(self) -> None:
        """Хук для восстановления состояния (для demo - заглушка)."""
        pass
    
    async def cleanup(self) -> None:
        """Очистка ресурсов сессии."""
        async with self.lock:
            if self.task and not self.task.done():
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
            self.task = None
            self.log.info(f"Session {self.session_id} cleaned up")
    
    def is_running(self) -> bool:
        """Проверяет, выполняется ли задача сессии."""
        return self.task is not None and not self.task.done()
    
    def touch(self) -> None:
        """Обновляет время последней активности."""
        self.last_active_at = datetime.now(timezone.utc)
    
    def get_age_seconds(self) -> float:
        """Возвращает возраст сессии в секундах."""
        now = datetime.now(timezone.utc)
        return (now - self.last_active_at).total_seconds()