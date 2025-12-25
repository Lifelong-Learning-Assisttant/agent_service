"""
Unit tests for AgentSystem session management methods.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

from agent_system import AgentSystem
from agent_session import AgentSession


class TestAgentSystemSessions:
    """Тесты для методов управления сессиями в AgentSystem."""
    
    @pytest.fixture
    def agent_system(self):
        """Фикстура для создания AgentSystem с моками."""
        with patch('agent_system.get_settings') as mock_get_settings, \
             patch('agent_system.LLMClient'), \
             patch('agent_system.make_tools'), \
             patch('agent_system.MemorySaver'), \
             patch('agent_system.StateGraph'):
            
            mock_cfg = Mock()
            mock_cfg.default_provider = "openai"
            mock_cfg.session_ttl_seconds = 600
            mock_cfg.concurrency_limit = 2
            mock_get_settings.return_value = mock_cfg
            
            system = AgentSystem()
            # Останавливаем sweeper для тестов
            if system._sweeper_task:
                system._sweeper_task.cancel()
            return system
    
    def test_create_session_new(self, agent_system):
        """Тест создания новой сессии."""
        session = agent_system.create_session("test_session")
        
        assert session is not None
        assert session.session_id == "test_session"
        assert session.parent == agent_system
        assert "test_session" in agent_system.sessions
        assert agent_system.sessions["test_session"] == session
    
    def test_create_session_existing(self, agent_system):
        """Тест получения существующей сессии."""
        session1 = agent_system.create_session("test_session")
        session2 = agent_system.create_session("test_session")
        
        assert session1 == session2
        assert len(agent_system.sessions) == 1
    
    def test_get_session_exists(self, agent_system):
        """Тест получения существующей сессии."""
        session = agent_system.create_session("test_session")
        retrieved = agent_system.get_session("test_session")
        
        assert retrieved == session
    
    def test_get_session_not_exists(self, agent_system):
        """Тест получения несуществующей сессии."""
        retrieved = agent_system.get_session("nonexistent")
        
        assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_remove_session(self, agent_system):
        """Тест удаления сессии."""
        session = agent_system.create_session("test_session")
        assert "test_session" in agent_system.sessions
        
        # Мокаем cleanup
        with patch.object(session, 'cleanup', new_callable=AsyncMock):
            agent_system.remove_session("test_session")
        
        assert "test_session" not in agent_system.sessions
    
    @pytest.mark.asyncio
    async def test_sweep_expired_sessions(self, agent_system):
        """Тест очистки старых сессий."""
        # Создаем сессии с разным временем активности
        now = datetime.now(timezone.utc)
        
        session1 = agent_system.create_session("active")
        session1.last_active_at = now
        
        session2 = agent_system.create_session("expired")
        session2.last_active_at = now - timedelta(seconds=700)  # Больше TTL
        
        session3 = agent_system.create_session("recently_expired")
        session3.last_active_at = now - timedelta(seconds=500)  # Меньше TTL
        
        # Мокаем cleanup
        with patch.object(session2, 'cleanup', new_callable=AsyncMock) as mock_cleanup:
            await agent_system.sweep_expired_sessions()
            mock_cleanup.assert_called_once()
        
        # Проверяем, что expired сессия удалена
        assert "active" in agent_system.sessions
        assert "expired" not in agent_system.sessions
        assert "recently_expired" in agent_system.sessions
    
    @pytest.mark.asyncio
    async def test_sweep_expired_sessions_empty(self, agent_system):
        """Тест очистки когда нет сессий."""
        await agent_system.sweep_expired_sessions()  # Не должен упасть
    
    @pytest.mark.asyncio
    async def test_run_with_new_session(self, agent_system):
        """Тест run с новой сессией."""
        with patch.object(agent_system, 'get_session', return_value=None), \
             patch.object(agent_system, 'create_session') as mock_create, \
             patch.object(agent_system, '_concurrency_sem') as mock_sem, \
             patch('asyncio.sleep', new_callable=AsyncMock):
            
            mock_session = Mock()
            mock_session.is_running.return_value = False
            mock_session.start = AsyncMock()
            mock_session.task = AsyncMock()
            mock_session.task.done.return_value = True
            mock_session.state = {"final_answer": "test answer"}
            mock_create.return_value = mock_session
            
            mock_sem.__aenter__ = AsyncMock()
            mock_sem.__aexit__ = AsyncMock()
            
            result = await agent_system.run("test question", "new_session")
            
            assert result == "test answer"
            mock_session.start.assert_called_once_with("test question")
    
    @pytest.mark.asyncio
    async def test_run_with_existing_session(self, agent_system):
        """Тест run с существующей сессией."""
        session = agent_system.create_session("existing")
        
        with patch.object(agent_system, '_concurrency_sem') as mock_sem, \
             patch('asyncio.sleep', new_callable=AsyncMock):
            
            # Мокаем выполнение сессии
            async def mock_start(question):
                session.state = {"final_answer": "answer"}
                session.task = Mock()
                session.task.done.return_value = True
            
            session.start = mock_start
            
            mock_sem.__aenter__ = AsyncMock()
            mock_sem.__aexit__ = AsyncMock()
            
            result = await agent_system.run("test question", "existing")
            
            assert result == "answer"
    
    @pytest.mark.asyncio
    async def test_run_when_session_busy(self, agent_system):
        """Тест run когда сессия занята."""
        session = agent_system.create_session("busy")
        session.task = Mock()
        session.task.done.return_value = False
        
        result = await agent_system.run("test question", "busy")
        
        assert "busy" in result.lower() or "wait" in result.lower()
    
    @pytest.mark.asyncio
    async def test_run_async(self, agent_system):
        """Тест run_async."""
        with patch.object(agent_system, 'get_session', return_value=None), \
             patch.object(agent_system, 'create_session') as mock_create:
            
            mock_session = Mock()
            mock_session.is_running.return_value = False
            mock_session.start = AsyncMock()
            mock_session.task = Mock()
            mock_create.return_value = mock_session
            
            task = await agent_system.run_async("test", "async_session")
            
            assert task == mock_session.task
            mock_session.start.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_concurrency_limit(self, agent_system):
        """Тест ограничения параллелизма."""
        # Проверяем, что семафор создан с правильным лимитом
        assert agent_system._concurrency_sem._value == 2
    
    @pytest.mark.asyncio
    async def test_sweeper_loop_error_handling(self, agent_system):
        """Тест обработки ошибок в sweeper."""
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep, \
             patch.object(agent_system, 'sweep_expired_sessions', side_effect=Exception("Test error")):
            
            # Запускаем sweeper
            sweeper_task = asyncio.create_task(agent_system._sweep_expired_sessions_loop())
            
            # Даем время для выполнения
            await asyncio.sleep(0.01)
            
            # Отменяем
            sweeper_task.cancel()
            try:
                await sweeper_task
            except asyncio.CancelledError:
                pass
            
            # Если не упал - значит ошибка была обработана
    
    def test_remove_session_with_event_loop(self, agent_system):
        """Тест remove_session с event loop."""
        session = agent_system.create_session("test")
        
        with patch.object(session, 'cleanup', new_callable=AsyncMock) as mock_cleanup:
            # Мокаем event loop
            mock_loop = Mock()
            mock_loop.is_running.return_value = True
            mock_loop.create_task = Mock()
            
            with patch('asyncio.get_event_loop', return_value=mock_loop):
                agent_system.remove_session("test")
                
                # Проверяем, что cleanup был запланирован
                mock_loop.create_task.assert_called_once()
    
    def test_remove_session_no_event_loop(self, agent_system):
        """Тест remove_session когда нет event loop."""
        session = agent_system.create_session("test")
        
        with patch('asyncio.get_event_loop', side_effect=RuntimeError("No loop")):
            # Не должен упасть
            agent_system.remove_session("test")
        
        assert "test" not in agent_system.sessions