#!/usr/bin/env python3
"""Тест для проверки пайплайна работы с RAG"""

import sys
import os

# Добавляем путь к модулям
sys.path.insert(0, '/app')

from agent_system import AgentSystem

def test_rag_pipeline():
    """Тестируем пайплайн работы с RAG"""
    print("=== Testing RAG Pipeline ===")
    
    # Создаем агент
    agent = AgentSystem()
    
    # Тест с вопросом, требующим поиска в RAG
    print("\n--- Testing RAG Search Question ---")
    try:
        result = agent.run("Расскажи о машинном обучении из учебника Яндекса", session_id="rag_session")
        print(f"Agent response: {result[:300]}...")
        assert len(result) > 0, "Ответ не должен быть пустым"
    except Exception as e:
        print(f"Agent error: {e}")
        raise
    
    # Тест с вопросом, требующим генерации ответа на основе RAG
    print("\n--- Testing RAG Generate Question ---")
    try:
        result = agent.run("Сгенерируй ответ о нейронных сетях на основе учебника Яндекса", session_id="rag_session")
        print(f"Agent response: {result[:300]}...")
        assert len(result) > 0, "Ответ не должен быть пустым"
    except Exception as e:
        print(f"Agent error: {e}")
        raise
    
    # Тест с вопросом, требующим поиска и генерации
    print("\n--- Testing RAG Search and Generate Question ---")
    try:
        result = agent.run("Найди информацию о глубоком обучении и сгенерируй ответ", session_id="rag_session")
        print(f"Agent response: {result[:300]}...")
        assert len(result) > 0, "Ответ не должен быть пустым"
    except Exception as e:
        print(f"Agent error: {e}")
        raise

if __name__ == "__main__":
    test_rag_pipeline()