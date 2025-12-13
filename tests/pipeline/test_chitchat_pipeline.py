#!/usr/bin/env python3
"""Тест для проверки пайплайна простого общения"""

import sys
import os

# Добавляем путь к модулям
sys.path.insert(0, os.path.dirname(__file__))

from agent_system import AgentSystem

def test_chitchat_pipeline():
    """Тестируем пайплайн простого общения"""
    print("=== Testing Chitchat Pipeline ===")
    
    # Создаем агент
    agent = AgentSystem()
    
    # Тест с простым вопросом
    print("\n--- Testing Simple Question ---")
    try:
        result = agent.run("Привет! Как дела?", session_id="chitchat_session")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с общим вопросом
    print("\n--- Testing General Question ---")
    try:
        result = agent.run("Расскажи о себе", session_id="chitchat_session")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")
    
    # Тест с вопросом о погоде
    print("\n--- Testing Weather Question ---")
    try:
        result = agent.run("Какая сегодня погода?", session_id="chitchat_session")
        print(f"Agent response: {result[:300]}...")
    except Exception as e:
        print(f"Agent error: {e}")

if __name__ == "__main__":
    test_chitchat_pipeline()