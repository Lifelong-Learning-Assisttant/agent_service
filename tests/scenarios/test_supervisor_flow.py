import pytest
import logging
import asyncio
from typing import Dict, Any

from graphs.supervisor import supervisor_graph, supervisor_node, route_from_supervisor
from state import AgentState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_supervisor_intent_routing():
    """Проверка маршрутизации Supervisor на основе интента."""
    
    # 1. Тест перехода в Quiz через команду
    state_quiz = {"question": "/answer [1]", "quiz_questions": [{"q": "Q1"}]}
    res_quiz = await supervisor_node(state_quiz)
    assert res_quiz["intent"] == "quiz"
    assert route_from_supervisor(res_quiz) == "quiz"
    
    # 2. Тест перехода в Algo (заглушка)
    state_algo = {"question": "Я хочу решить задачу на алгоритмы"}
    # Имитируем что LLM вернула algo
    res_algo = {"intent": "algo"}
    assert route_from_supervisor(res_algo) == "algo_placeholder"
    
    # 3. Тест перехода в Search (теория)
    state_search = {"question": "Расскажи про трансформеры"}
    # Имитируем что LLM вернула search
    res_search = {"intent": "search"}
    assert route_from_supervisor(res_search) == "search"
    
    logger.info("✅ test_supervisor_intent_routing passed")

@pytest.mark.asyncio
async def test_supervisor_full_flow_quiz():
    """Интеграционный тест Supervisor -> Quiz Subgraph."""
    initial_state = {
        "question": "/answer [0]",
        "quiz_questions": [{"q": "Q1", "correct_indices": [0], "a": "A1"}],
        "current_quiz_index": 0,
        "quiz_history": [],
        "interaction_mode": "ANSWER_QUIZ"
    }
    
    # Запускаем весь граф через ainvoke
    # Примечание: для работы ainvoke нужен MemorySaver и thread_id
    from langgraph.checkpoint.memory import MemorySaver
    memory = MemorySaver()
    app = supervisor_graph
    
    config = {"configurable": {"thread_id": "test_thread"}}
    
    # Шаг 1: Ответ на вопрос
    final_state = await app.ainvoke(initial_state, config=config)
    
    assert "final_answer" in final_state
    assert "Результаты квиза" in final_state["final_answer"]
    # Проверяем что история была использована (хотя ментор ее очищает в конце,
    # в final_state она может остаться если не было явного удаления из TypedDict или если мы смотрим промежуточный стейт)
    # В текущем quiz.py mentor возвращает пустой quiz_history.
    assert final_state["quiz_history"] == []
    assert final_state["intent"] == "evaluate_quiz" # После последнего вопроса
    
    logger.info("✅ test_supervisor_full_flow_quiz passed")

if __name__ == "__main__":
    async def run():
        await test_supervisor_intent_routing()
        await test_supervisor_full_flow_quiz()
    asyncio.run(run())