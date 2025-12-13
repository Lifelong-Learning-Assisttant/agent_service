#!/usr/bin/env python3
"""
Простой скрипт для тестирования запросов к OpenRouter API.
Использует API-ключ из .env файла.
"""

import os
import requests
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Получаем API-ключ для OpenRouter
OPENROUTER_API_KEY = os.getenv("LLM_OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    print("Ошибка: API-ключ для OpenRouter не найден в .env файле.")
    exit(1)

# Настройки запроса
url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}
data = {
    "model": "kwaipilot/kat-coder-pro:free",
    "messages": [
        {"role": "user", "content": "Привет! Как дела?"}
    ],
}

# Отправляем запрос
try:
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    print("Успешный ответ от OpenRouter:")
    print(f"Модель: {result.get('model')}")
    print(f"Ответ: {result['choices'][0]['message']['content']}")
except requests.exceptions.RequestException as e:
    print(f"Ошибка при отправке запроса: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Код ошибки: {e.response.status_code}")
        print(f"Ответ: {e.response.text}")