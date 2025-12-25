#!/usr/bin/env python3
"""Тест для проверки асинхронных инструментов RAG"""

import sys
import os
import asyncio
import json

# Добавляем путь к модулям
sys.path.insert(0, os.path.dirname(__file__))

from langchain_tools import rag_search_async, rag_generate_async
from settings import get_settings

async def test_rag_tools_async():
    """Тестируем асинхронные инструменты RAG"""
    settings = get_settings()
    
    print("=== Testing Async RAG Tools ===")
    print(f"RAG Service URL: {settings.rag_service_url}")
    
    # Тест поиска
    print("\n--- Testing rag_search_async ---")
    try:
        result = await rag_search_async("тестирование поиска", top_k=3)
        result_dict = json.loads(result)
        if "error" in result_dict:
            print(f"Search error: {result_dict['error']}")
        else:
            print(f"Search result: {result[:200]}...")
    except Exception as e:
        print(f"Search error: {e}")
    
    # Тест генерации
    print("\n--- Testing rag_generate_async ---")
    try:
        result = await rag_generate_async("тестирование генерации", top_k=3)
        result_dict = json.loads(result)
        if "error" in result_dict:
            print(f"Generate error: {result_dict['error']}")
        else:
            print(f"Generate result: {result[:200]}...")
    except Exception as e:
        print(f"Generate error: {e}")

if __name__ == "__main__":
    asyncio.run(test_rag_tools_async())