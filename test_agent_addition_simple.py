#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы агента с инструментом сложения (простой вариант).
"""

import os
import logging
from context7_agent import Context7AgentSystem

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def test_agent_addition_simple():
    """Тестирует работу агента с инструментом сложения (простой вопрос)."""
    
    log.info("Creating agent...")
    agent = Context7AgentSystem()
    
    # Задаем простой вопрос о сложении
    question = "Сколько будет 8 плюс 12?"
    
    log.info(f"Asking agent: {question}")
    
    try:
        result = agent.run(question)
        log.info(f"Agent response: {result}")
        
        # Проверяем, что ответ содержит правильную сумму
        if "20" in result or "двадцать" in result.lower():
            log.info("✅ Agent correctly calculated sum")
            return True
        else:
            log.error(f"❌ Agent did not calculate correctly. Response: {result}")
            return False
            
    except Exception as e:
        log.error(f"❌ Agent test failed with error: {e}")
        return False

if __name__ == "__main__":
    success = test_agent_addition_simple()
    exit(0 if success else 1)