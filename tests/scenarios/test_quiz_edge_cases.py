import pytest
import logging
import asyncio
from typing import Dict, Any
from langgraph.checkpoint.memory import MemorySaver
from graphs.supervisor import supervisor_graph
from state import AgentState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_quiz_interrupt_finish():
    """Сценарий: Прерывание квиза командой /finish_quizz на середине."""
    memory = MemorySaver()
    app = supervisor_graph
    config = {"configurable": {"thread_id": "test_interrupt"}}
    
    # Исходное состояние: квиз из 3 вопросов, мы на первом
    initial_state = {
        "quiz_questions": [
            {"q": "Q1", "correct_indices": [0], "a": "A1"},
            {"q": "Q2", "correct_indices": [1], "a": "A2"},
            {"q": "Q3", "correct_indices": [0], "a": "A3"}
        ],
        "current_quiz_index": 0,
        "quiz_history": [],
        "interaction_mode": "ANSWER_QUIZ",
        "question": "/finish_quizz"
    }
    
    final_state = await app.ainvoke(initial_state, config=config)
    
    assert "📊 **Результаты квиза**" in final_state["final_answer"]
    assert "Всего вопросов: 0" in final_state["final_answer"] # Т.к. ни один не отвечен
    assert final_state["quiz_questions"] == [] # Состояние должно очиститься
    logger.info("✅ test_quiz_interrupt_finish passed")

@pytest.mark.asyncio
async def test_quiz_skip_all():
    """Сценарий: Пропуск всех вопросов через /skip_question."""
    memory = MemorySaver()
    app = supervisor_graph
    config = {"configurable": {"thread_id": "test_skip_all"}}
    
    state = {
        "quiz_questions": [
            {"q": "Q1", "a": "A1"},
            {"q": "Q2", "a": "A2"}
        ],
        "current_quiz_index": 0,
        "quiz_history": [],
        "interaction_mode": "ANSWER_QUIZ",
        "question": "/skip_question"
    }
    
    # Пропускаем первый
    s1 = await app.ainvoke(state, config=config)
    assert "[SYSTEM: NEXT_QUESTION]" in s1["final_answer"]
    assert s1["current_quiz_index"] == 1
    
    # Пропускаем второй (последний)
    s2 = await app.ainvoke({"question": "/skip_question"}, config=config)
    assert "📊 **Результаты квиза**" in s2["final_answer"]
    assert "Верных ответов: 0" in s2["final_answer"]
    logger.info("✅ test_quiz_skip_all passed")

@pytest.mark.asyncio
async def test_quiz_invalid_answer_format():
    """Сценарий: Обработка некорректных ответов (невалидный формат в /answer)."""
    memory = MemorySaver()
    app = supervisor_graph
    config = {"configurable": {"thread_id": "test_invalid_format"}}
    
    state = {
        "quiz_questions": [{"q": "Что такое градиент?", "a": "Вектор"}],
        "current_quiz_index": 0,
        "quiz_history": [],
        "interaction_mode": "ANSWER_QUIZ",
        "question": "/answer [не число]"
    }
    
    # Должно упасть в open_judge и обработаться LLM или вернуть ошибку парсинга, но не сломать граф
    final_state = await app.ainvoke(state, config=config)
    
    assert "final_answer" in final_state
    # В mcq_judge_node есть try-except который при ошибке вызывает open_judge_node
    logger.info("✅ test_quiz_invalid_answer_format passed")

@pytest.mark.asyncio
async def test_quiz_rag_clarification_and_resume():
    """Сценарий: RAG уточнение во время активного квиза и возврат контекста."""
    memory = MemorySaver()
    app = supervisor_graph
    config = {"configurable": {"thread_id": "test_rag_resume"}}
    
    state = {
        "quiz_questions": [{"q": "Как работает Adam?", "a": "Это адаптивный метод..."}],
        "current_quiz_index": 0,
        "quiz_history": [],
        "interaction_mode": "AI_SYNC",
        "question": "А что такое Adam?"
    }
    
    # 1. Задаем вопрос. Должен сработать RAG (intent: rag_answer -> interviewer_hint)
    s1 = await app.ainvoke(state, config=config)
    
    # Проверяем что ответ пришел от подсказчика (interviewer_hint)
    # В quiz.py interviewer_hint_node возвращает подсказку.
    assert s1["current_quiz_index"] == 0
    assert "final_answer" in s1
    
    # 2. Теперь отвечаем на вопрос квиза
    s2 = await app.ainvoke({"question": "Это метод оптимизации", "interaction_mode": "ANSWER_QUIZ"}, config=config)
    
    assert "📊 **Результаты квиза**" in s2["final_answer"]
    logger.info("✅ test_quiz_rag_clarification_and_resume passed")

if __name__ == "__main__":
    async def run():
        await test_quiz_interrupt_finish()
        await test_quiz_skip_all()
        await test_quiz_invalid_answer_format()
        await test_quiz_rag_clarification_and_resume()
    asyncio.run(run())