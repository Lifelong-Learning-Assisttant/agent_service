#!/usr/bin/env python3
"""
Диагностический скрипт для проверки сетевого подключения к Tavily серверу
"""

import socket
import subprocess
import httpx

def test_dns_resolution():
    """Тестируем разрешение DNS имени tavily"""
    print("=== Тестирование разрешения DNS ===")
    try:
        ip = socket.gethostbyname("tavily")
        print(f"✅ DNS разрешение успешно: tavily -> {ip}")
        return True
    except socket.gaierror as e:
        print(f"❌ DNS разрешение не удалось: {e}")
        return False

def test_tcp_connection():
    """Тестируем TCP соединение с Tavily сервером"""
    print("\n=== Тестирование TCP соединения ===")
    try:
        sock = socket.create_connection(("tavily", 8000), timeout=5)
        print(f"✅ TCP соединение успешно установлено")
        sock.close()
        return True
    except Exception as e:
        print(f"❌ TCP соединение не удалось: {e}")
        return False

def test_http_connection():
    """Тестируем HTTP соединение с Tavily сервером"""
    print("\n=== Тестирование HTTP соединения ===")
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get("http://tavily:8000")
            print(f"✅ HTTP соединение успешно (HTTP {response.status_code})")
            return True
    except Exception as e:
        print(f"❌ HTTP соединение не удалось: {e}")
        return False

def test_mcp_request():
    """Тестируем MCP запрос"""
    print("\n=== Тестирование MCP запроса ===")
    try:
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        
        with httpx.Client(timeout=5) as client:
            response = client.post("http://tavily:8000", json=message)
            print(f"✅ MCP запрос успешно (HTTP {response.status_code})")
            print(f"Ответ: {response.text[:200]}...")
            return True
    except Exception as e:
        print(f"❌ MCP запрос не удалось: {e}")
        return False

def main():
    """Основная функция диагностики"""
    print("=== Диагностика сетевого подключения к Tavily серверу ===\n")
    
    # Тестируем DNS
    dns_ok = test_dns_resolution()
    
    # Тестируем TCP
    tcp_ok = test_tcp_connection()
    
    # Тестируем HTTP
    http_ok = test_http_connection()
    
    # Тестируем MCP
    mcp_ok = test_mcp_request()
    
    print("\n=== Результаты диагностики ===")
    print(f"DNS разрешение: {'✅' if dns_ok else '❌'}")
    print(f"TCP соединение: {'✅' if tcp_ok else '❌'}")
    print(f"HTTP соединение: {'✅' if http_ok else '❌'}")
    print(f"MCP запрос: {'✅' if mcp_ok else '❌'}")
    
    if not dns_ok:
        print("\n🔧 Рекомендации:")
        print("1. Проверьте, что оба контейнера в одной Docker сети")
        print("2. Запустите: docker network inspect tavily_search_tool_network")
        print("3. Убедитесь, что контейнер tavily_server запущен")
    elif not tcp_ok:
        print("\n🔧 Рекомендации:")
        print("1. Проверьте, что tavily_server слушает на порту 8000")
        print("2. Запустите: docker exec -it tavily_server netstat -tuln")
        print("3. Проверьте логи: docker logs tavily_server")
    elif not http_ok:
        print("\n🔧 Рекомендации:")
        print("1. Проверьте, что Tavily сервер правильно настроен")
        print("2. Убедитесь, что TAVILY_API_KEY указан в .env файле")
        print("3. Проверьте логи: docker logs tavily_server")
    else:
        print("\n✅ Все тесты пройдены! Tavily сервер доступен.")

if __name__ == "__main__":
    main()