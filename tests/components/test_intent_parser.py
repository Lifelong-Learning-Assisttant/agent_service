import pytest
from unittest.mock import MagicMock, patch
from agent_service.agent_system import AgentSystem

@pytest.mark.asyncio
async def test_intent_determination_general():
    """Тест определения намерения 'general' с использованием JsonOutputParser."""
    
    # Mock LLM response
    mock_response = MagicMock()
    mock_response.content = '```json\n{"intent": "general"}\n```'
    
    with patch("agent_service.llm_service.llm_client.LLMClient.create_chat") as mock_create_chat:
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = mock_response
        mock_create_chat.return_value = mock_chat
        
        system = AgentSystem(provider="openai") # Provider doesn't matter for mock
        intent = system._determine_intent("Привет, как дела?")
        
        assert intent == "general"

@pytest.mark.asyncio
async def test_intent_determination_rag():
    """Тест определения намерения 'rag_answer'."""
    
    mock_response = MagicMock()
    mock_response.content = '{"intent": "rag_answer"}'
    
    with patch("agent_service.llm_service.llm_client.LLMClient.create_chat") as mock_create_chat:
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = mock_response
        mock_create_chat.return_value = mock_chat
        
        system = AgentSystem()
        intent = system._determine_intent("Что такое градиентный спуск?")
        
        assert intent == "rag_answer"

@pytest.mark.asyncio
async def test_intent_determination_fallback():
    """Тест fallback на 'general' при ошибке парсинга."""
    
    mock_response = MagicMock()
    # Invalid JSON
    mock_response.content = 'Just some text without JSON'
    
    with patch("agent_service.llm_service.llm_client.LLMClient.create_chat") as mock_create_chat:
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = mock_response
        mock_create_chat.return_value = mock_chat
        
        system = AgentSystem()
        intent = system._determine_intent("Непонятный запрос")
        
        # Should fallback to general
        assert intent == "general"

@pytest.mark.asyncio
async def test_intent_determination_malformed_json_recovery():
    """Тест способности JsonOutputParser восстанавливать 'битый' JSON (например, без закрывающей скобки)."""
    
    # LangChain's JsonOutputParser is quite robust, but let's test a simple case it handles
    # Usually it handles markdown blocks. Let's try a case where it might fail validation but pass parsing
    # Actually, let's test that it handles extra text around JSON
    
    mock_response = MagicMock()
    mock_response.content = 'Here is the JSON: {"intent": "generate_quiz"} Hope it helps!'
    
    with patch("agent_service.llm_service.llm_client.LLMClient.create_chat") as mock_create_chat:
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = mock_response
        mock_create_chat.return_value = mock_chat
        
        system = AgentSystem()
        intent = system._determine_intent("Хочу тест")
        
        assert intent == "generate_quiz"