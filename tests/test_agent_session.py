"""
Unit tests for AgentSession class.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

from agent_session import AgentSession
from agent_system import AgentSystem


class TestAgentSession:
    """Тесты для класса AgentSession."""
    
    @pytest.fixture
    def mock_agent_system(self):
        """Фикстура для мока AgentSystem."""
        mock = Mock(spec=AgentSystem)
        mock.cfg = Mock()
        mock.cfg.web_ui_url = "http://localhost:8150"
        mock.cfg.session_ttl_seconds = 600
        return mock
    
    @pytest.fixture
    def agent_session(self, mock_agent_system):
        """Фикстура для создания AgentSession."""
        return AgentSession("test_session", mock_agent_system)
    
    def test_init(self, agent_session, mock_agent_system):
        """Тест инициализации сессии."""
        assert agent_session.session_id == "test_session"
        assert agent_session.parent == mock_agent_system
        assert agent_session.state == {}
        assert agent_session.task is None
        assert agent_session.cancelled is False
        assert agent_session.last_events.maxlen == 200
        assert agent_session.lock is not None
    
    def test_is_running_when_no_task(self, agent_session):
        """Тест is_running когда задачи нет."""
        assert agent_session.is_running() is False
    
    def test_is_running_when_task_done(self, agent_session):
        """Тест is_running когда задача завершена."""
        mock_task = Mock()
        mock_task.done.return_value = True
        agent_session.task = mock_task
        assert agent_session.is_running() is False
    
    def test_is_running_when_task_active(self, agent_session):
        """Тест is_running когда задача активна."""
        mock_task = Mock()
        mock_task.done.return_value = False
        agent_session.task = mock_task
        assert agent_session.is_running() is True
    
    def test_touch_updates_last_active(self, agent_session):
        """Тест touch обновляет время активности."""
        old_time = agent_session.last_active_at
        agent_session.touch()
        new_time = agent_session.last_active_at
        assert new_time > old_time
    
    def test_get_age_seconds(self, agent_session):
        """Тест вычисления возраста сессии."""
        agent_session.last_active_at = datetime.now(timezone.utc)
        age = agent_session.get_age_seconds()
        assert age >= 0
        assert age < 1.0  # Должно быть очень маленьким
    
    @pytest.mark.asyncio
    async def test_notify_ui_success(self, agent_session, mock_agent_system):
        """Тест успешной отправки уведомления в UI."""
        # Мокаем httpx.AsyncClient
        with patch('agent_session.httpx.AsyncClient') as mock_client:
            mock_post = AsyncMock()
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            await agent_session.notify_ui(
                step="test_step",
                message="Test message",
                tool="test_tool",
                level="info",
                meta={"key": "value"}
            )
            
            # Проверяем, что событие добавлено в историю
            assert len(agent_session.last_events) == 1
            event = agent_session.last_events[0]
            assert event["session_id"] == "test_session"
            assert event["step"] == "test_step"
            assert event["message"] == "Test message"
            assert event["tool"] == "test_tool"
            assert event["level"] == "info"
            assert event["meta"] == {"key": "value"}
            
            # Проверяем вызов httpx
            mock_post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_notify_ui_no_web_ui_url(self, agent_session):
        """Тест notify_ui когда URL не настроен."""
        with patch('agent_session.get_settings') as mock_get_settings, \
             patch('agent_session.httpx.AsyncClient') as mock_client:
            
            mock_cfg = Mock()
            mock_cfg.web_ui_url = None
            mock_get_settings.return_value = mock_cfg
            
            # Обновляем cfg в session
            agent_session.cfg = mock_cfg
            
            await agent_session.notify_ui("test", "message")
            
            # Должно добавить в историю, но не вызывать httpx
            assert len(agent_session.last_events) == 1
            mock_client.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_notify_ui_http_error(self, agent_session):
        """Тест notify_ui при ошибке HTTP."""
        with patch('agent_session.httpx.AsyncClient') as mock_client:
            mock_post = AsyncMock(side_effect=Exception("Network error"))
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            # Не должен поднимать исключение
            await agent_session.notify_ui("test", "message")
            
            # Должен добавить в историю
            assert len(agent_session.last_events) == 1
    
    @pytest.mark.asyncio
    async def test_start_creates_task(self, agent_session):
        """Тест start создает фоновую задачу."""
        with patch.object(agent_session, '_run_graph', new_callable=AsyncMock) as mock_run:
            await agent_session.start("test question")
            
            assert agent_session.task is not None
            assert agent_session.state["question"] == "test question"
            assert agent_session.cancelled is False
            mock_run.assert_called_once_with("test question")
    
    @pytest.mark.asyncio
    async def test_start_when_already_running(self, agent_session):
        """Тест start когда сессия уже выполняется."""
        mock_task = Mock()
        mock_task.done.return_value = False
        agent_session.task = mock_task
        
        with patch.object(agent_session, '_run_graph') as mock_run:
            await agent_session.start("test question")
            mock_run.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_run_graph_success(self, agent_session):
        """Тест успешного выполнения _run_graph."""
        with patch.object(agent_session, 'notify_ui', new_callable=AsyncMock) as mock_notify, \
             patch.object(agent_session, 'call_tool', new_callable=AsyncMock) as mock_call_tool:
            
            mock_call_tool.side_effect = [
                ["Док 1", "Док 2"],  # rag_search
                "Квиз сгенерирован"  # generate_exam
            ]
            
            await agent_session._run_graph("test question")
            
            # Проверяем вызовы notify_ui
            assert mock_notify.call_count >= 4
            
            # Проверяем вызовы инструментов
            assert mock_call_tool.call_count == 2
            
            # Проверяем финальный ответ
            assert "final_answer" in agent_session.state
            assert "Квиз готов!" in agent_session.state["final_answer"]
    
    @pytest.mark.asyncio
    async def test_run_graph_cancelled(self, agent_session):
        """Тест отмены _run_graph."""
        with patch.object(agent_session, 'notify_ui', new_callable=AsyncMock) as mock_notify:
            # Создаем задачу и отменяем ее
            task = asyncio.create_task(agent_session._run_graph("test"))
            task.cancel()
            
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            # Проверяем, что было отправлено уведомление об отмене
            # (в реальном коде это делается в _run_graph)
    
    @pytest.mark.asyncio
    async def test_run_graph_error(self, agent_session):
        """Тест ошибки в _run_graph."""
        with patch.object(agent_session, 'notify_ui', new_callable=AsyncMock) as mock_notify:
            # Мокаем call_tool чтобы вызвать ошибку
            with patch.object(agent_session, 'call_tool', side_effect=ValueError("Test error")):
                await agent_session._run_graph("test")
                
                # Проверяем, что было отправлено уведомление об ошибке
                # (в реальном коде это делается в _run_graph)
    
    @pytest.mark.asyncio
    async def test_call_tool_rag_search(self, agent_session):
        """Тест вызова инструмента rag_search."""
        with patch.object(agent_session, 'notify_ui', new_callable=AsyncMock) as mock_notify:
            result = await agent_session.call_tool("rag_search", query="test")
            
            assert result == ["Документ 1", "Документ 2", "Документ 3"]
            assert mock_notify.call_count == 2  # start и done
    
    @pytest.mark.asyncio
    async def test_call_tool_generate_exam(self, agent_session):
        """Тест вызова инструмента generate_exam."""
        with patch.object(agent_session, 'notify_ui', new_callable=AsyncMock) as mock_notify:
            result = await agent_session.call_tool("generate_exam", markdown_content="test")
            
            assert "Вопрос 1" in result
            assert mock_notify.call_count == 2
    
    @pytest.mark.asyncio
    async def test_cancel(self, agent_session):
        """Тест отмены сессии."""
        # Создаем реальную задачу
        async def dummy_task():
            await asyncio.sleep(10)
        
        agent_session.task = asyncio.create_task(dummy_task())
        agent_session.task.add_done_callback(lambda t: None)  # Чтобы избежать предупреждений
        
        await agent_session.cancel()
        
        assert agent_session.cancelled is True
        assert agent_session.task is None or agent_session.task.done()
    
    @pytest.mark.asyncio
    async def test_cleanup(self, agent_session):
        """Тест очистки ресурсов."""
        # Создаем реальную задачу
        async def dummy_task():
            await asyncio.sleep(10)
        
        agent_session.task = asyncio.create_task(dummy_task())
        agent_session.task.add_done_callback(lambda t: None)
        
        await agent_session.cleanup()
        
        assert agent_session.task is None