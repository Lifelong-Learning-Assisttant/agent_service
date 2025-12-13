#!/usr/bin/env python3
"""
Тестовый скрипт для проверки интеграции Context7 MCP сервера.
"""

import os
import logging
from langchain_tools import context7_search
from settings import get_settings

# Настройка логирования
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Загрузка настроек
settings = get_settings()

def test_context7_integration():
    """Тестирует интеграцию с Context7 MCP сервером."""
    
    # Проверяем URL Context7
    context7_url = settings.context7_url or os.environ.get("CONTEXT7_URL", "http://context7:8000")
    log.info(f"Testing Context7 integration with URL: {context7_url}")
    
    try:
        # Тестовый запрос
        query = "How to use React hooks"
        library_name = "vercel/next.js"
        
        log.info(f"Sending test query: {query}")
        log.info(f"Library: {library_name}")
        
        # Выполняем поиск (используем query и library_name)
        result = context7_search(query, library_name)
         
        log.info(f"Context7 search result:\n{result}")
         
        # Проверяем, что получили осмысленный ответ
        # Успешный ответ содержит реальные данные, а не обертку "Context7"
        if len(result) > 50:
            log.info("✅ Context7 integration test PASSED")
            return True
        else:
            log.error("❌ Context7 integration test FAILED - unexpected response")
            return False
            
    except Exception as e:
        log.error(f"❌ Context7 integration test FAILED with error: {e}")
        return False

if __name__ == "__main__":
    success = test_context7_integration()
    exit(0 if success else 1)