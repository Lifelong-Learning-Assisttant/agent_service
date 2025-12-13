#!/usr/bin/env python3
"""Тест для проверки пайплайна работы с квизами"""

import sys
import os

# Добавляем путь к модулям
sys.path.insert(0, '/app')

from agent_system import AgentSystem

def test_quiz_pipeline():
    """Тестируем пайплайн работы с квизами"""
    print("=== Testing Quiz Pipeline ===")
    
    # Создаем агент
    agent = AgentSystem()
    
    # Тест с генерацией квиза
    print("\n--- Testing Quiz Generation ---")
    try:
        result = agent.run("Создай квиз по машинному обучению из учебника Яндекса", session_id="quiz_session")
        print(f"Generated quiz: {result[:300]}...")
        assert len(result) > 0, "Ответ не должен быть пустым"
    except Exception as e:
        print(f"Agent error: {e}")
        raise
    
    # Тест с оценкой квиза
    print("\n--- Testing Quiz Evaluation ---")
    try:
        # Предполагаем, что квиз уже сгенерирован в предыдущем шаге
        result = agent.run("Вот мои ответы на квиз: ответ 1, ответ 2", session_id="quiz_session")
        print(f"Evaluation result: {result[:300]}...")
        assert len(result) > 0, "Ответ не должен быть пустым"
    except Exception as e:
        print(f"Agent error: {e}")
        raise
    
    # Тест с полным циклом: генерация квиза и оценка
    print("\n--- Testing Full Quiz Cycle ---")
    try:
        # Генерируем квиз
        quiz_result = agent.run("Создай квиз по глубокому обучению", session_id="full_quiz_session")
        print(f"Generated quiz: {quiz_result[:200]}...")
        assert len(quiz_result) > 0, "Ответ не должен быть пустым"
        
        # Оцениваем ответ
        evaluation_result = agent.run("Вот мои ответы на квиз: ответ 1, ответ 2", session_id="full_quiz_session")
        print(f"Evaluation result: {evaluation_result[:200]}...")
        assert len(evaluation_result) > 0, "Ответ не должен быть пустым"
    except Exception as e:
        print(f"Agent error: {e}")
        raise

if __name__ == "__main__":
    test_quiz_pipeline()