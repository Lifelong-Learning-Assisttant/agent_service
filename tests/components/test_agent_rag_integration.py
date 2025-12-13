#!/usr/bin/env python3
"""Тест для проверки интеграции RAG инструментов в агент"""

import sys
import os

# Добавляем путь к модулям
sys.path.insert(0, os.path.dirname(__file__))

from agent_system import AgentSystem

def test_agent_with_rag():
    """Тестируем работу агента с инструментами RAG"""
    print("=== Testing Agent with RAG Tools ===")
    
    # Создаем агент
    agent = AgentSystem()
    
    # Тест с инструментом поиска RAG
    print("\n--- Testing RAG Search ---")
    try:
        result = agent.run("Используй инструмент rag_search для поиска информации о машинном обучении", session_id="test_session_1")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с инструментом генерации RAG
    print("\n--- Testing RAG Generate ---")
    try:
        result = agent.run("Используй инструмент rag_generate для генерации ответа о машинном обучении", session_id="test_session_2")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с прямым вопросом
    print("\n--- Testing Direct Question ---")
    try:
        result = agent.run("Что такое машинное обучение?", session_id="test_session_3")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с генерацией квиза
    print("\n--- Testing Quiz Generation ---")
    try:
        result = agent.run("Создай квиз по машинному обучению", session_id="test_session_4")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с оценкой квиза
    print("\n--- Testing Quiz Evaluation ---")
    try:
        # Сначала создаем квиз
        quiz_result = agent.run("Создай квиз по машинному обучению", session_id="test_session_5")
        print(f"Quiz generated: {quiz_result[:200]}...")
        
        # Затем оцениваем ответ
        evaluation_result = agent.run("Вот мои ответы на квиз: ответ 1, ответ 2", session_id="test_session_5")
        print(f"Evaluation result: {evaluation_result[:200]}...")
    except Exception as e:
        print(f"Agent error: {e}")

if __name__ == "__main__":
    test_agent_with_rag()