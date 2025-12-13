#!/usr/bin/env python3
"""Тест для проверки работы инструментов RAG"""

import sys
import os

# Добавляем путь к модулям
sys.path.insert(0, os.path.dirname(__file__))

from langchain_tools import rag_search, rag_generate
from settings import get_settings

def test_rag_tools():
    """Тестируем инструменты RAG"""
    settings = get_settings()
    
    print("=== Testing RAG Tools ===")
    print(f"RAG Service URL: {settings.rag_service_url}")
    
    # Тест поиска
    print("\n--- Testing rag_search ---")
    try:
        result = rag_search("тестирование поиска", top_k=3)
        print(f"Search result: {result[:200]}...")
    except Exception as e:
        print(f"Search error: {e}")
    
    # Тест генерации
    print("\n--- Testing rag_generate ---")
    try:
        result = rag_generate("тестирование генерации", top_k=3)
        print(f"Generate result: {result[:200]}...")
    except Exception as e:
        print(f"Generate error: {e}")

if __name__ == "__main__":
    test_rag_tools()