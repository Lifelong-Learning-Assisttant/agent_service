#!/usr/bin/env python3
"""
Тестовый скрипт для проверки интеграции Tavily MCP сервера через mcp-remote.
"""
import json
import subprocess
import sys
import os

def test_tavily_mcp_remote():
    print("=== Тестирование интеграции Tavily MCP сервера через mcp-remote ===\n")
    
    # Проверяем, что контейнер tavily_server запущен
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=tavily_server", "--format", "{{.Names}}"],
            capture_output=True,
            text=True
        )
        if "tavily_server" not in result.stdout:
            print("❌ Контейнер tavily_server не запущен")
            return
        print("✅ Контейнер tavily_server запущен")
    except Exception as e:
        print(f"❌ Ошибка проверки контейнера: {e}")
        return
    
    # Тест 1: Поиск через mcp-remote
    print("\n1. Тест поиска: Что такое LangChain?")
    try:
        # Создаем MCP-запрос
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tavily-search",
                "arguments": {
                    "query": "Что такое LangChain?",
                    "search_depth": "basic",
                    "topic": "general",
                    "max_results": 5
                }
            }
        }
        
        # Выполняем запрос через mcp-remote
        result = subprocess.run(
            ["docker", "exec", "-i", "tavily_server", "npx", "-y", "mcp-remote", "http://localhost:8000"],
            input=json.dumps(message),
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            print(f"✅ Результат: {data}")
        else:
            print(f"❌ Ошибка: {result.stderr}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    # Тест 2: Поиск через mcp-remote
    print("\n2. Тест поиска: Как использовать MCP протокол?")
    try:
        # Создаем MCP-запрос
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tavily-search",
                "arguments": {
                    "query": "Как использовать MCP протокол?",
                    "search_depth": "basic",
                    "topic": "general",
                    "max_results": 5
                }
            }
        }
        
        # Выполняем запрос через mcp-remote
        result = subprocess.run(
            ["docker", "exec", "-i", "tavily_server", "npx", "-y", "mcp-remote", "http://localhost:8000"],
            input=json.dumps(message),
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            print(f"✅ Результат: {data}")
        else:
            print(f"❌ Ошибка: {result.stderr}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
