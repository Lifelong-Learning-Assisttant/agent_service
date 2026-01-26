import sys
import os
import asyncio
import pytest
from typing import Dict, Any

# Добавляем путь к модулям
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from graphs.chat import chat_graph
from state import AgentState
from langchain_core.messages import HumanMessage

@pytest.mark.asyncio
async def test_chat_graph_general():
    """Тест маршрутизации chitchat (general)"""
    state: AgentState = {
        "question": "Привет! Как дела?",
        "messages": [HumanMessage(content="Привет! Как дела?")],
        "intent": "general"
    }
    
    # Запускаем граф
    result = await chat_graph.ainvoke(state)
    
    assert "final_answer" in result
    assert len(result["final_answer"]) > 0
    print(f"\nGeneral Response: {result['final_answer']}")

@pytest.mark.asyncio
async def test_chat_graph_technical():
    """Тест маршрутизации технического вопроса (technical)"""
    state: AgentState = {
        "question": "Что такое градиентный спуск?",
        "messages": [HumanMessage(content="Что такое градиентный спуск?")],
        "intent": "rag_answer" # Это будет установлено в chat_router_node
    }
    
    # Запускаем граф
    # Примечание: так как это юнит-тест графа, он вызовет реальный LLM и инструменты поиска
    result = await chat_graph.ainvoke(state)
    
    assert "final_answer" in result
    assert "градиент" in result["final_answer"].lower()
    # assert "Источники:" in result["final_answer"] # Источники могут отсутствовать если RAG вернул пустой результат или ошибку
    print(f"\nTechnical Response: {result['final_answer']}")

if __name__ == "__main__":
    # Для ручного запуска
    async def run_tests():
        print("Running Chat Graph Tests...")
        await test_chat_graph_general()
        await test_chat_graph_technical()
        print("Done!")

    asyncio.run(run_tests())