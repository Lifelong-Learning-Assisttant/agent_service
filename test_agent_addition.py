#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы агента с инструментом сложения.
"""

import os
import logging
from context7_agent import Context7AgentSystem

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def test_agent_addition():
    """Тестирует работу агента с инструментом сложения."""
    
    log.info("Creating agent...")
    agent = Context7AgentSystem()
    
    # Задаем вопрос, который требует использования инструмента сложения
    question = "Сколько будет 15 плюс 27? Используй инструмент addition_service."
    
    log.info(f"Asking agent: {question}")
    
    try:
        result = agent.run(question)
        log.info(f"Agent response: {result}")
        
        # Проверяем, что ответ содержит правильную сумму
        if "42" in result or "сорок два" in result.lower():
            log.info("✅ Agent correctly used addition service")
            return True
        else:
            log.error(f"❌ Agent did not use addition service correctly. Response: {result}")
            return False
            
    except Exception as e:
        log.error(f"❌ Agent test failed with error: {e}")
        return False

if __name__ == "__main__":
    success = test_agent_addition()
    exit(0 if success else 1)