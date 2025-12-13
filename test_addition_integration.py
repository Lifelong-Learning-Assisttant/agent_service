#!/usr/bin/env python3
"""
Тестовый скрипт для проверки интеграции сервиса сложения.
"""

import os
import logging
from langchain_tools import addition_service
from settings import get_settings

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Загрузка настроек
settings = get_settings()

def test_addition_integration():
    """Тестирует интеграцию с сервисом сложения."""
    
    # Проверяем URL сервиса сложения
    addition_service_url = settings.addition_service_url or os.environ.get("ADDITION_SERVICE_URL", "http://localhost:8000")
    log.info(f"Testing addition service integration with URL: {addition_service_url}")
    
    try:
        # Тест 1: простые числа
        log.info("Test 1: 5 + 7")
        result1 = addition_service(5, 7)
        log.info(f"Result: {result1}")
        assert result1 == 12.0, f"Expected 12.0, got {result1}"
        
        # Тест 2: отрицательные числа
        log.info("Test 2: -3 + 10")
        result2 = addition_service(-3, 10)
        log.info(f"Result: {result2}")
        assert result2 == 7.0, f"Expected 7.0, got {result2}"
        
        # Тест 3: дробные числа
        log.info("Test 3: 2.5 + 3.5")
        result3 = addition_service(2.5, 3.5)
        log.info(f"Result: {result3}")
        assert result3 == 6.0, f"Expected 6.0, got {result3}"
        
        log.info("✅ Addition service integration test PASSED")
        return True
        
    except Exception as e:
        log.error(f"❌ Addition service integration test FAILED with error: {e}")
        return False

if __name__ == "__main__":
    success = test_addition_integration()
    exit(0 if success else 1)