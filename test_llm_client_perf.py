import time
import os
import sys
from langchain_core.messages import HumanMessage

# Добавляем путь к модулям
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from llm_service.llm_client import LLMClient
from settings import get_settings

def test_llm_client_performance():
    print("=== Testing LLM Client Performance ===")
    
    # 1. Инициализация
    start_time = time.time()
    settings = get_settings()
    client = LLMClient(provider="openai")
    chat = client.create_chat(temperature=0)
    init_time = time.time() - start_time
    print(f"Initialization time: {init_time:.4f}s")
    
    # 2. Выполнение запроса
    print("\nSending request...")
    start_req_time = time.time()
    try:
        res = chat.invoke([HumanMessage(content="Why is the sky blue?")])
        req_time = time.time() - start_req_time
        print(f"Request time: {req_time:.4f}s")
        print(f"Response length: {len(res.content)} chars")
        print("Response preview:", res.content[:100] + "...")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_llm_client_performance()