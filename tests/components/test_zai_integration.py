import pytest
from llm_service.llm_client import LLMClient
from settings import get_settings

def test_zai_client_initialization():
    """Проверка инициализации клиента Z.ai."""
    client = LLMClient(provider="zai")
    assert client.provider == "zai"
    
    settings = get_settings()
    # Проверяем, что модель по умолчанию из настроек подхватывается корректно
    model = client._chat_model_for_provider("zai", None)
    assert model == "glm-4.7"

def test_zai_chat_creation():
    """Проверка создания чат-объекта для Z.ai."""
    client = LLMClient(provider="zai")
    # Передаем фейковый ключ, чтобы не зависеть от .env при юнит-тесте
    chat = client.create_chat(api_key="sk-fake-key")
    
    # ChatOpenAI используется как база для Z.ai
    from langchain_openai import ChatOpenAI
    assert isinstance(chat, ChatOpenAI)
    assert chat.model_name == "glm-4.7"
    assert str(chat.openai_api_base) == "https://api.z.ai/v1"

def test_zai_embeddings_creation():
    """Проверка создания объекта эмбеддингов для Z.ai."""
    client = LLMClient(provider="zai")
    embeddings = client.create_embeddings(api_key="sk-fake-key")
    
    from langchain_openai import OpenAIEmbeddings
    assert isinstance(embeddings, OpenAIEmbeddings)
    assert embeddings.model == "text-embedding-3-small"
    assert str(embeddings.openai_api_base) == "https://api.z.ai/v1"