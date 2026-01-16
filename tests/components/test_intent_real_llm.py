import pytest
from agent_system import AgentSystem

@pytest.mark.asyncio
async def test_intent_real_llm_general():
    """Тест определения намерения 'general' на реальной LLM."""
    system = AgentSystem()
    # Ожидаем general для простого приветствия
    intent = system._determine_intent("Привет! Расскажи анекдот.")
    print(f"\nВопрос: Привет! Расскажи анекдот. -> Намерение: {intent}")
    assert intent in ["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering"]
    assert intent == "general"

@pytest.mark.asyncio
async def test_intent_real_llm_rag():
    """Тест определения намерения 'rag_answer' на реальной LLM."""
    system = AgentSystem()
    # Ожидаем rag_answer для вопроса по ML
    intent = system._determine_intent("Что такое переобучение (overfitting) в нейронных сетях?")
    print(f"\nВопрос: Что такое переобучение? -> Намерение: {intent}")
    assert intent == "rag_answer"

@pytest.mark.asyncio
async def test_intent_real_llm_quiz():
    """Тест определения намерения 'generate_quiz' на реальной LLM."""
    system = AgentSystem()
    # Ожидаем generate_quiz для запроса на тест
    intent = system._determine_intent("Я хочу пройти тест по машинному обучению.")
    print(f"\nВопрос: Хочу пройти тест. -> Намерение: {intent}")
    assert intent == "generate_quiz"