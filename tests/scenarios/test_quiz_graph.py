import pytest
import os
import json
import logging
import asyncio
from datetime import datetime
from graphs.quiz import quiz_graph
from state import AgentState
from langchain_core.messages import HumanMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def save_test_log(scenario_name: str, state: dict):
    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(logs_dir, f"quiz_scenario_{scenario_name}_{timestamp}.json")
    
    serializable_state = {}
    for k, v in state.items():
        try:
            json.dumps(v)
            serializable_state[k] = v
        except:
            serializable_state[k] = str(v)

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(serializable_state, f, ensure_ascii=False, indent=2)
    logger.info(f"📝 Лог сценария сохранен: {log_file}")

@pytest.mark.asyncio
async def test_quiz_full_flow():
    """Сценарий: Полное прохождение квиза (2 вопроса)."""
    scenario = "full_flow"
    logger.info(f"🚀 Запуск сценария: {scenario}")
    
    # Имитируем состояние после create_quiz_node
    initial_state: AgentState = {
        "quiz_questions": [
            {"q": "Что такое градиент?", "a": "Вектор наискорейшего роста"},
            {"q": "Что такое ReLU?", "a": "Функция активации max(0, x)"}
        ],
        "current_quiz_index": 0,
        "user_answers": [],
        "question": "Это вектор", # Ответ на 1-й вопрос
        "intent": "quiz_answering"
    }
    
    # 1. Отвечаем на первый вопрос
    logger.info("Шаг 1: Ответ на первый вопрос")
    state2 = await quiz_graph.ainvoke(initial_state)
    assert state2["current_quiz_index"] == 1
    assert len(state2["user_answers"]) == 1
    assert "NEXT_QUESTION" in state2["final_answer"]
    
    # 2. Отвечаем на второй вопрос
    logger.info("Шаг 2: Ответ на второй вопрос")
    state2["question"] = "Это функция активации"
    state3 = await quiz_graph.ainvoke(state2)
    
    # После 2-го ответа он должен был уйти в mentor
    assert len(state3["quiz_questions"]) == 0
    assert "Результаты квиза" in state3["final_answer"]
    
    save_test_log(scenario, state3)
    logger.info("✅ Сценарий full_flow успешно завершен")

@pytest.mark.asyncio
async def test_quiz_with_hint():
    """Сценарий: Запрос подсказки во время квиза."""
    scenario = "hint_flow"
    logger.info(f"🚀 Запуск сценария: {scenario}")
    
    initial_state: AgentState = {
        "quiz_questions": [
            {"q": "Что такое градиент?", "a": "Вектор наискорейшего роста"}
        ],
        "current_quiz_index": 0,
        "user_answers": [],
        "question": "Я не знаю, дай подсказку",
        "intent": "quiz_answering", # Роутер должен переопределить или мы имитируем вызов после роутера
        "prepared_material": "Градиент — это вектор, указывающий направление наискорейшего возрастания функции."
    }
    
    # Сначала прогоним через роутер (внутри ainvoke он есть)
    # Но для теста подсказки нам нужно, чтобы роутер вернул intent=quiz_answering и были документы (имитация RAG)
    # Или мы можем проверить сам узел interviewer_node
    
    # Имитируем, что роутер распознал help и мы сходили в retrieval
    initial_state["intent"] = "quiz_answering"
    initial_state["documents"] = [{"content": "Градиент - это вектор...", "source": "test"}]
    
    final_state = await quiz_graph.ainvoke(initial_state)
    
    assert "final_answer" in final_state
    assert initial_state["current_quiz_index"] == 0 # Индекс не должен измениться
    assert len(final_state["user_answers"]) == 0 # Ответ не должен быть засчитан
    
    save_test_log(scenario, final_state)
    logger.info("✅ Сценарий hint_flow успешно завершен")

@pytest.mark.asyncio
async def test_quiz_skip():
    """Сценарий: Пропуск вопроса."""
    scenario = "skip_flow"
    logger.info(f"🚀 Запуск сценария: {scenario}")
    
    initial_state: AgentState = {
        "quiz_questions": [
            {"q": "Вопрос 1", "a": "Ответ 1"},
            {"q": "Вопрос 2", "a": "Ответ 2"}
        ],
        "current_quiz_index": 0,
        "user_answers": [],
        "question": "/skip_question",
        "intent": "skip_question"
    }
    
    final_state = await quiz_graph.ainvoke(initial_state)
    
    assert final_state["current_quiz_index"] == 1
    assert final_state["user_answers"][0] == "[SYSTEM: SKIPPED]"
    
    save_test_log(scenario, final_state)
    logger.info("✅ Сценарий skip_flow успешно завершен")

if __name__ == "__main__":
    async def run():
        await test_quiz_full_flow()
        await test_quiz_with_hint()
        await test_quiz_skip()
    asyncio.run(run())