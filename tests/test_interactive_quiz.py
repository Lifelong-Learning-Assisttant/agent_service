#!/usr/bin/env python3
"""
Тест интерактивного квиза для новой системы агента.
Добавлена расширенная отладка и логирование истории.
"""

import asyncio
import json
import sys
import os
import logging
from datetime import datetime

# Добавляем путь к корневой директории agent_service
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_system import AgentSystem
from agent_session import AgentSession
from settings import get_settings

# Настройка логирования для теста
log_dir = os.path.join(os.path.dirname(__file__), "scenarios", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"quiz_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("QuizTest")

async def log_step(step_name, user_input, agent_output, state=None):
    logger.info(f"\n" + "="*40)
    logger.info(f"ШАГ: {step_name}")
    logger.info(f"ПОЛЬЗОВАТЕЛЬ: {user_input}")
    logger.info(f"АГЕНТ: {agent_output}")
    if state:
        # Извлекаем только важные поля состояния
        quiz_state = {
            "current_index": state.get("current_quiz_index"),
            "questions_count": len(state.get("quiz_questions", [])),
            "answers_count": len(state.get("user_answers", [])),
            "intent": state.get("intent")
        }
        logger.info(f"СОСТОЯНИЕ: {json.dumps(quiz_state, ensure_ascii=False)}")
    logger.info("="*40)

async def test_interactive_quiz():
    """Тест интерактивного квиза через основной API."""
    
    logger.info("Запуск теста интерактивного квиза...")
    
    # 1. Инициализация системы
    system = AgentSystem()
    session_id = f"test_quiz_{datetime.now().strftime('%H%M%S')}"
    session = system.create_session(session_id)
    
    # 2. Запуск квиза
    quiz_request = "Сгенерируй квиз по основам нейросетей, 2 вопроса"
    logger.info(f"Отправка запроса: {quiz_request}")
    
    result = await system.run(quiz_request, session_id)
    state = system.get_session(session_id).state
    await log_step("ГЕНЕРАЦИЯ КВИЗА", quiz_request, result, state)
    
    # Проверка, что квиз начался
    if not state.get("quiz_questions"):
        logger.error("Квиз не был сгенерирован!")
        return False

    # 3. Ответ на первый вопрос
    answer1 = "Это функция активации"
    logger.info(f"Ответ 1: {answer1}")
    result = await system.run(answer1, session_id)
    state = system.get_session(session_id).state
    await log_step("ОТВЕТ 1", answer1, result, state)

    # 4. Запрос подсказки (тестируем новый роутер)
    help_request = "Я не уверен, можно подсказку?"
    logger.info(f"Запрос подсказки: {help_request}")
    result = await system.run(help_request, session_id)
    state = system.get_session(session_id).state
    await log_step("ПОДСКАЗКА", help_request, result, state)
    
    # Проверка, что индекс не изменился после подсказки
    if state.get("current_quiz_index") != 1:
        logger.warning(f"Индекс изменился после подсказки! Ожидался 1, получили {state.get('current_quiz_index')}")

    # 5. Ответ на второй вопрос
    answer2 = "Метод обратного распространения ошибки"
    logger.info(f"Ответ 2: {answer2}")
    result = await system.run(answer2, session_id)
    state = system.get_session(session_id).state
    await log_step("ОТВЕТ 2", answer2, result, state)

    # 6. Финальная проверка
    logger.info("Проверка завершения квиза...")
    if len(state.get("quiz_questions", [])) == 0:
        logger.info("✓ Квиз успешно завершен и состояние очищено")
    else:
        logger.error("✗ Состояние квиза не очищено после завершения!")
        return False

    if "Результаты квиза" in result or "📊" in result:
        logger.info("✓ Получен финальный отчет")
    else:
        logger.error("✗ Финальный отчет не содержит ожидаемых маркеров")
        return False

    logger.info("ТЕСТ УСПЕШНО ЗАВЕРШЕН")
    return True

if __name__ == "__main__":
    asyncio.run(test_interactive_quiz())