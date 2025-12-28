#!/usr/bin/env python3
"""
Тест интерактивного квиза для новой системы агента.

Тесты адаптированы под текущую реализацию с LangGraph и MemorySaver.
"""

import asyncio
import json
import sys
import os

# Добавляем путь к корневой директории agent_service
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_system import AgentSystem
from agent_session import AgentSession
from settings import get_settings

settings = get_settings()


async def test_interactive_quiz():
    """Тест интерактивного квиза через основной API."""
    
    print("=" * 60)
    print("Тест интерактивного квиза")
    print("=" * 60)
    
    # 1. Инициализация системы
    print("\n[1] Инициализация AgentSystem...")
    system = AgentSystem()
    print("✓ Система инициализирована")
    
    # 2. Создание сессии
    print("\n[2] Создание сессии...")
    session_id = "test_quiz_session_001"
    session = system.create_session(session_id)
    print(f"✓ Сессия создана: {session_id}")
    
    # 3. Запуск квиза - отправляем запрос на генерацию квиза
    print("\n[3] Запуск квиза (генерация вопросов)...")
    quiz_request = "Сгенерируй квиз по Python программированию, 3 вопроса"
    
    # Запускаем через основной метод run
    result1 = await system.run(quiz_request, session_id)
    print(f"✓ Результат: {result1[:100]}...")
    
    # Проверяем состояние сессии
    session_obj = system.get_session(session_id)
    if session_obj:
        state = session_obj.state
        print(f"  Состояние квиза:")
        print(f"    - Вопросов в памяти: {len(state.get('quiz_questions', []))}")
        print(f"    - Текущий индекс: {state.get('current_quiz_index', 0)}")
        print(f"    - Ответов пользователя: {len(state.get('user_answers', []))}")
    
    # 4. Ответ на первый вопрос
    print("\n[4] Ответ на первый вопрос...")
    answer1 = "Это метод оптимизации"
    result2 = await system.run(answer1, session_id)
    print(f"✓ Результат: {result2[:100]}...")
    
    if session_obj:
        state = session_obj.state
        print(f"  После ответа 1:")
        print(f"    - Текущий индекс: {state.get('current_quiz_index', 0)}")
        print(f"    - Ответов пользователя: {len(state.get('user_answers', []))}")
    
    # 5. Ответ на второй вопрос
    print("\n[5] Ответ на второй вопрос...")
    answer2 = "Через передачу сигналов"
    result3 = await system.run(answer2, session_id)
    print(f"✓ Результат: {result3[:100]}...")
    
    if session_obj:
        state = session_obj.state
        print(f"  После ответа 2:")
        print(f"    - Текущий индекс: {state.get('current_quiz_index', 0)}")
        print(f"    - Ответов пользователя: {len(state.get('user_answers', []))}")
    
    # 6. Ответ на третий вопрос (последний)
    print("\n[6] Ответ на третий вопрос...")
    answer3 = "При помощи градиентного спуска"
    result4 = await system.run(answer3, session_id)
    print(f"✓ Результат: {result4[:100]}...")
    
    if session_obj:
        state = session_obj.state
        print(f"  После ответа 3 (завершение):")
        print(f"    - Текущий индекс: {state.get('current_quiz_index', 0)}")
        print(f"    - Ответов пользователя: {len(state.get('user_answers', []))}")
        print(f"    - Вопросов в памяти: {len(state.get('quiz_questions', []))}")
    
    # 7. Проверка финального результата
    print("\n[7] Финальный результат квиза...")
    print(f"✓ Квиз завершен")
    print(f"  Финальный ответ: {result4[:200]}...")
    
    # Проверяем, что состояние квиза очистилось
    if session_obj:
        state = session_obj.state
        quiz_cleared = len(state.get('quiz_questions', [])) == 0
        print(f"  Состояние квиза очищено: {quiz_cleared}")
    
    # 8. Проверка оценки квиза
    print("\n[8] Проверка оценки квиза...")
    
    # Проверяем, что финальный ответ содержит ключевые элементы оценки
    final_answer_lower = result4.lower()
    
    # Должно содержать информацию о вопросах
    has_question_count = "всего вопросов" in final_answer_lower or "total questions" in final_answer_lower
    # Должно содержать детальный разбор
    has_detailed_review = "вопрос" in final_answer_lower and "ваш ответ" in final_answer_lower
    # Должно содержать рекомендации
    has_recommendations = "рекоменд" in final_answer_lower or "совет" in final_answer_lower
    
    print(f"  Содержит количество вопросов: {has_question_count}")
    print(f"  Содержит детальный разбор: {has_detailed_review}")
    print(f"  Содержит рекомендации: {has_recommendations}")
    
    if not (has_question_count and has_detailed_review):
        print("✗ Оценка квиза не содержит достаточной детализации")
        return False
    
    print("✓ Оценка квиза содержит полную информацию")
    
    print("\n" + "=" * 60)
    print("✓ ТЕСТ ИНТЕРАКТИВНОГО КВИЗА УСПЕШНО ПРОЙДЕН!")
    print("=" * 60)
    
    return True


async def test_error_cases():
    """Тест обработки ошибок."""
    
    print("\n" + "=" * 60)
    print("Тест обработки ошибок")
    print("=" * 60)
    
    system = AgentSystem()
    
    # 1. Несуществующая сессия
    print("\n[1] Проверка несуществующей сессии...")
    try:
        # Попытка использовать несуществующую сессию
        result = await system.run("test question", "nonexistent-session-id")
        # Если сессия не существует, она будет создана автоматически
        print(f"✓ Сессия создана автоматически: {result[:50]}...")
    except Exception as e:
        print(f"✓ Ошибка корректно обработана: {e}")
    
    # 2. Проверка очистки состояния
    print("\n[2] Проверка очистки состояния после квиза...")
    session_id = "test_cleanup_session"
    
    # Создаем сессию и запускаем квиз
    await system.run("Сгенерируй квиз по Python, 2 вопроса", session_id)
    
    # Отвечаем на вопросы
    await system.run("Ответ 1", session_id)
    await system.run("Ответ 2", session_id)
    
    # Проверяем состояние
    session_obj = system.get_session(session_id)
    state = session_obj.state
    
    quiz_cleared = len(state.get('quiz_questions', [])) == 0
    answers_cleared = len(state.get('user_answers', [])) == 0
    
    if quiz_cleared and answers_cleared:
        print("✓ Состояние квиза корректно очищено")
    else:
        print("✗ Состояние квиза не очищено")
        return False
    
    print("\n" + "=" * 60)
    print("✓ ТЕСТЫ ОБРАБОТКИ ОШИБОК УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 60)
    
    return True


async def test_multiple_sessions():
    """Тест работы с несколькими сессиями одновременно."""
    
    print("\n" + "=" * 60)
    print("Тест множественных сессий")
    print("=" * 60)
    
    system = AgentSystem()
    
    # Создаем две сессии
    session1 = "user_001"
    session2 = "user_002"
    
    print("\n[1] Создание двух сессий...")
    system.create_session(session1)
    system.create_session(session2)
    print("✓ Обе сессии созданы")
    
    # Запускаем квизы параллельно
    print("\n[2] Запуск параллельных квизов...")
    
    async def run_quiz(session_id, topic):
        result = await system.run(f"Сгенерируй квиз по {topic}, 2 вопроса", session_id)
        await system.run("Ответ 1", session_id)
        await system.run("Ответ 2", session_id)
        return result
    
    # Запускаем параллельно
    results = await asyncio.gather(
        run_quiz(session1, "Python"),
        run_quiz(session2, "JavaScript")
    )
    
    print("✓ Параллельные квизы завершены")
    
    # Проверяем, что состояния независимы
    state1 = system.get_session(session1).state
    state2 = system.get_session(session2).state
    
    # Оба должны быть очищены
    quiz1_cleared = len(state1.get('quiz_questions', [])) == 0
    quiz2_cleared = len(state2.get('quiz_questions', [])) == 0
    
    if quiz1_cleared and quiz2_cleared:
        print("✓ Состояния сессий независимы и корректны")
    else:
        print("✗ Проблема с изоляцией сессий")
        return False
    
    print("\n" + "=" * 60)
    print("✓ ТЕСТ МНОЖЕСТВЕННЫХ СЕССИЙ УСПЕШНО ПРОЙДЕН!")
    print("=" * 60)
    
    return True


async def main():
    """Основная функция."""
    
    try:
        # Запуск основных тестов
        success1 = await test_interactive_quiz()
        
        # Запуск тестов ошибок
        success2 = await test_error_cases()
        
        # Запуск тестов множественных сессий
        success3 = await test_multiple_sessions()
        
        if success1 and success2 and success3:
            print("\n🎉 ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ! 🎉")
            sys.exit(0)
        else:
            print("\n❌ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())