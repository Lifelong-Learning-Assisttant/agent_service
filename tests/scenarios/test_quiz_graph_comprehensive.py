import pytest
import os
import json
import logging
import asyncio
import re
from datetime import datetime
from typing import Dict, Any, Optional

from graphs.quiz import quiz_graph, quiz_router_node, mcq_judge_node, open_judge_node, explainer_node, skip_node, check_progress_node, mentor_node
from state import AgentState
from langchain_core.messages import HumanMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Вспомогательные классы ---

class MockSession:
    """Заглушка для AgentSession для захвата UI уведомлений."""
    def __init__(self):
        self.events = []
    
    async def notify_ui(self, step, message, tool=None, level="info", meta=None):
        event = {
            "step": step,
            "message": message,
            "tool": tool,
            "level": level,
            "meta": meta or {}
        }
        self.events.append(event)
        logger.info(f"UI NOTIFICATION: {step} - {message}")

# --- Тесты узлов (Unit Tests) ---

@pytest.mark.asyncio
async def test_quiz_router_deterministic():
    """Проверка детерминированного роутинга (v3.5)."""
    
    # 1. MCQ ответ (Regex)
    state = {"question": "/answer [0, 2]"}
    res = await quiz_router_node(state)
    assert res["intent"] == "quiz_answering"
    
    # 2. Режим ANSWER_QUIZ (Открытый ответ)
    state = {"question": "Это нейронная сеть", "interaction_mode": "ANSWER_QUIZ"}
    res = await quiz_router_node(state)
    assert res["intent"] == "quiz_answering"
    
    # 3. Режим AI_SYNC + вопрос (Search)
    state = {"question": "А как работает Adam?", "interaction_mode": "AI_SYNC"}
    res = await quiz_router_node(state)
    assert res["intent"] == "rag_answer"
    
    logger.info("✅ test_quiz_router_deterministic passed")

@pytest.mark.asyncio
async def test_mcq_judge_correct():
    """Проверка алгоритмического MCQ судьи (Верный ответ)."""
    state = {
        "current_quiz_index": 0,
        "quiz_questions": [{"q": "Q1", "correct_indices": [0, 2]}],
        "question": "/answer [0, 2]",
        "quiz_history": []
    }
    res = await mcq_judge_node(state)
    assert res["last_evaluation"]["is_correct"] is True
    assert res["last_evaluation"]["score"] == 1.0
    assert len(res["quiz_history"]) == 1
    logger.info("✅ test_mcq_judge_correct passed")

@pytest.mark.asyncio
async def test_mcq_judge_incorrect():
    """Проверка алгоритмического MCQ судьи (Неверный ответ)."""
    state = {
        "current_quiz_index": 0,
        "quiz_questions": [{"q": "Q1", "correct_indices": [0, 2]}],
        "question": "/answer [0, 1]",
        "quiz_history": []
    }
    res = await mcq_judge_node(state)
    assert res["last_evaluation"]["is_correct"] is False
    assert res["last_evaluation"]["score"] == 0.0
    logger.info("✅ test_mcq_judge_incorrect passed")

@pytest.mark.asyncio
async def test_open_judge_real_llm():
    """Проверка LLM-судьи для открытых вопросов."""
    state = {
        "current_quiz_index": 0,
        "quiz_questions": [{"q": "Что такое градиентный спуск?", "a": "Метод поиска локального минимума функции с помощью производной"}],
        "question": "Это когда мы идем по антиградиенту чтобы найти минимум",
        "quiz_history": []
    }
    res = await open_judge_node(state)
    assert "is_correct" in res["last_evaluation"]
    assert res["last_evaluation"]["score"] > 0.5
    assert len(res["last_evaluation"]["reasoning"]) > 0
    logger.info("✅ test_open_judge_real_llm passed")

@pytest.mark.asyncio
async def test_explainer_node_generation():
    """Проверка генерации пояснений."""
    state = {
        "last_evaluation": {"is_correct": True, "reasoning": "Правильно определена суть."},
        "current_quiz_index": 0,
        "quiz_questions": [{"q": "Q1", "a": "Correct Answer"}]
    }
    res = await explainer_node(state)
    assert "Верно" in res["final_answer"]
    assert len(res["final_answer"]) > 20
    logger.info("✅ test_explainer_node_generation passed")

@pytest.mark.asyncio
async def test_mentor_with_history():
    """Проверка Ментора, использующего накопленную историю."""
    history = [
        {"index": 0, "question": "Q1", "user_input": "A1", "is_correct": True, "score": 1.0, "reasoning": "Good"},
        {"index": 1, "question": "Q2", "user_input": "A2", "is_correct": False, "score": 0.0, "reasoning": "Bad"}
    ]
    state = {
        "quiz_history": history,
        "quiz_questions": [{"q": "Q1"}, {"q": "Q2"}] # Еще не очищено
    }
    res = await mentor_node(state)
    assert "📊 **Результаты квиза**" in res["final_answer"]
    assert "Верных ответов: 1" in res["final_answer"]
    assert res["quiz_questions"] == [] # Должно очиститься
    logger.info("✅ test_mentor_with_history passed")

# --- Тесты графа (Flow Tests) ---

@pytest.mark.asyncio
async def test_full_mcq_flow():
    """Полный цикл MCQ: Router -> MCQ_Judge -> Explainer -> CheckProgress."""
    initial_state = {
        "quiz_questions": [{"q": "Q1", "correct_indices": [1]}],
        "current_quiz_index": 0,
        "user_answers": [],
        "quiz_history": [],
        "question": "/answer [1]",
        "interaction_mode": "ANSWER_QUIZ"
    }
    
    # Прогоняем через весь граф (или цепочку узлов для скорости)
    # 1. Router
    s1 = await quiz_router_node(initial_state)
    # 2. Judge (выбирается по префиксу /answer)
    s2 = await mcq_judge_node({**initial_state, **s1})
    # 3. Explainer
    s3 = await explainer_node({**initial_state, **s1, **s2})
    # 4. Progress
    s4 = await check_progress_node({**initial_state, **s1, **s2, **s3})
    
    assert s2["last_evaluation"]["is_correct"] is True
    assert "Верно" in s3["final_answer"]
    assert s4["intent"] == "evaluate_quiz" # Т.к. был всего 1 вопрос
    
    logger.info("✅ test_full_mcq_flow passed")

@pytest.mark.asyncio
async def test_quiz_skip_scenario():
    """Проверка сценария пропуска вопроса."""
    state = {
        "quiz_questions": [{"q": "Q1", "a": "A1"}],
        "current_quiz_index": 0,
        "quiz_history": [],
        "question": "/skip_question"
    }
    
    # 1. Router
    s1 = await quiz_router_node(state)
    assert s1["intent"] == "skip_question"
    
    # 2. Skip Node
    s2 = await skip_node({**state, **s1})
    assert s2["quiz_history"][0]["type"] == "skip"
    
    # 3. Progress Check
    s3 = await check_progress_node({**state, **s1, **s2})
    assert s3["intent"] == "evaluate_quiz"
    
    logger.info("✅ test_quiz_skip_scenario passed")

@pytest.mark.asyncio
async def test_quiz_hint_scenario():
    """Проверка сценария получения подсказки."""
    state = {
        "quiz_questions": [{"q": "Как работает свертка?", "a": "A1"}],
        "current_quiz_index": 0,
        "question": "Дай подсказку",
        "interaction_mode": "AI_SYNC",
        "prepared_material": "Свертка — это математическая операция..."
    }
    
    # 1. Router (LLM fallback)
    s1 = await quiz_router_node(state)
    # LLM должна определить 'help' -> 'quiz_answering' (в текущей реализации)
    # Но в route_quiz это пойдет в open_judge.
    # В Stage 3 было: Intent: Search -> Q_Search -> Q_Hint.
    # В quiz.py: route_quiz для rag_answer возвращает search.
    
    state["intent"] = "rag_answer" # Имитируем что роутер или LLM решили искать
    from graphs.quiz import route_quiz
    assert route_quiz(state) == "search"
    
    from graphs.quiz import interviewer_hint_node
    s_hint = await interviewer_hint_node(state)
    assert "final_answer" in s_hint
    assert len(s_hint["final_answer"]) > 0
    
    logger.info("✅ test_quiz_hint_scenario passed")

@pytest.mark.asyncio
async def test_supervisor_to_quiz_handoff():
    """Проверка передачи управления из Supervisor в Quiz."""
    from graphs.supervisor import supervisor_node, route_from_supervisor
    
    state = {
        "question": "Я хочу пройти тест по нейронкам",
        "quiz_questions": [],
        "interaction_mode": "AI_SYNC"
    }
    
    # 1. Supervisor определяет интент
    s1 = await supervisor_node(state)
    # Вероятно решит 'quiz' или 'chat' (если нет вопросов).
    # Но если мы шлем команду /answer - точно quiz.
    
    state_ans = {**state, "question": "/answer [0]"}
    s2 = await supervisor_node(state_ans)
    assert s2["intent"] == "quiz"
    assert route_from_supervisor(s2) == "quiz"
    
    logger.info("✅ test_supervisor_to_quiz_handoff passed")

@pytest.mark.asyncio
async def test_algo_placeholder_navigation():
    """Проверка заглушки для алго-собеседований."""
    from graphs.supervisor import supervisor_node, route_from_supervisor, algo_placeholder_node
    
    state = {
        "question": "Хочу алго-собеседование",
        "interaction_mode": "AI_SYNC"
    }
    
    # Имитируем решение супервизора
    s_intent = {"intent": "algo"}
    assert route_from_supervisor(s_intent) == "algo_placeholder"
    
    res = await algo_placeholder_node(state)
    assert "разработке" in res["final_answer"]
    
    logger.info("✅ test_algo_placeholder_navigation passed")

if __name__ == "__main__":
    async def run():
        await test_quiz_router_deterministic()
        await test_mcq_judge_correct()
        await test_mcq_judge_incorrect()
        await test_open_judge_real_llm()
        await test_explainer_node_generation()
        await test_mentor_with_history()
        await test_full_mcq_flow()
        await test_quiz_skip_scenario()
        await test_quiz_hint_scenario()
        await test_supervisor_to_quiz_handoff()
        await test_algo_placeholder_navigation()
    asyncio.run(run())
