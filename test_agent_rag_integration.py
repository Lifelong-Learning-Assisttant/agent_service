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
        result = agent.run("Используй инструмент rag_search для поиска информации о машинном обучении")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с инструментом генерации RAG
    print("\n--- Testing RAG Generate ---")
    try:
        result = agent.run("Используй инструмент rag_generate для генерации ответа о машинном обучении")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с прямым вопросом
    print("\n--- Testing Direct Question ---")
    try:
        result = agent.run("Что такое машинное обучение?")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")

if __name__ == "__main__":
    test_agent_with_rag()