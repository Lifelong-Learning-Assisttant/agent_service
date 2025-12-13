#!/usr/bin/env python3
"""
Тестирование интеграции Tavily MCP сервера с agent_service
"""

import sys
import os
from langchain_tools import tavily_search, make_tools
from langchain_agent import LangchainAgentService
 
# Читаем URL из переменной окружения с дефолтным значением
TAVILY_URL = os.getenv("TAVILY_URL", "http://tavily:8000")
 
def test_tavily_direct():
    """Тестируем прямой вызов Tavily поиска"""
    print("=== Тестирование прямого вызова Tavily поиска ===\n")
    
    # В Docker контейнере проверяем доступность сервера по сети
    try:
        import httpx
        # Пробуем подключиться к Tavily серверу
        with httpx.Client(timeout=5) as client:
            response = client.get(TAVILY_URL)
            print(f"✅ Tavily сервер доступен (HTTP {response.status_code})")
    except Exception as e:
        print(f"ℹ️  Не удалось проверить доступность сервера: {e}")
        print("ℹ️  Продолжаем тестирование - сервер может быть доступен")
    
    # Тест 1: Простой поисковый запрос
    print("\n1. Тест поиска: Что такое LangChain?")
    try:
        result = tavily_search("Что такое LangChain?")
        if "Tavily" in result and "error" not in result.lower():
            print(f"✅ Результат: {result[:200]}...")
        else:
            print(f"❌ Ошибка в результате: {result}")
            return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False
    
    # Тест 2: Более сложный запрос
    print("\n2. Тест поиска: Как использовать MCP протокол?")
    try:
        result = tavily_search("Как использовать MCP протокол?")
        if "Tavily" in result and "error" not in result.lower():
            print(f"✅ Результат: {result[:200]}...")
        else:
            print(f"❌ Ошибка в результате: {result}")
            return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False
    
    return True

def test_tavily_with_agent():
    """Тестируем использование Tavily в LangChain агенте"""
    print("\n=== Тестирование Tavily в LangChain агенте ===\n")
    
    try:
        # Создаем агент с инструментами
        agent = LangchainAgentService(verbose=True)
        
        # Тестируем запрос, который должен использовать Tavily
        print("Тест агента: Что такое LangChain и для чего он используется?")
        result = agent.run("Что такое LangChain и для чего он используется?")
        print(f"✅ Ответ агента: {result[:300]}...")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка при работе с агентом: {e}")
        return False

def test_tools_list():
    """Тестируем получение списка инструментов"""
    print("\n=== Тестирование списка инструментов ===\n")
    
    try:
        tools = make_tools()
        print(f"✅ Доступные инструменты ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при получении инструментов: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("=== Тестирование интеграции Tavily MCP сервера ===\n")
    
    # Тестируем прямые вызовы
    if not test_tavily_direct():
        print("\n❌ Тестирование прямого вызова не удалось")
        sys.exit(1)
    
    # Тестируем список инструментов
    if not test_tools_list():
        print("\n❌ Тестирование списка инструментов не удалось")
        sys.exit(1)
    
    # Тестируем работу с агентом
    if not test_tavily_with_agent():
        print("\n❌ Тестирование с агентом не удалось")
        sys.exit(1)
    
    print("\n🎉 Все тесты пройдены успешно!")
    print("Tavily MCP сервер успешно интегрирован с agent_service")

if __name__ == "__main__":
    main()