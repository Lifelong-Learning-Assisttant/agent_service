# Этап 3: Quiz Subgraph (Режим обучения v3.5)

## Цель
Реализовать подграф для проведения квизов (`Quiz Subgraph`) с гибридной системой оценки и детерминированным роутингом. Поддерживать роли Интервьюера-Судьи и Ментора.

## Задачи

### 1. Реализация узлов (Nodes)
- [x] **Quiz Router Node**:
    *   Алгоритмический роутинг по маркеру `/answer`.
    *   Разделение по `interaction_mode` (ANSWER_QUIZ vs AI_SYNC).
- [x] **MCQ Judge Node**:
    *   Алгоритмическая проверка индексов ответов.
    *   Сохранение результата в `quiz_history`.
- [x] **Open-ended Judge Node**:
    *   LLM-as-a-Judge для оценки текстовых ответов.
    *   Генерация `score` и `reasoning`.
- [x] **Explainer Node**:
    *   Генерация мгновенных пояснений после каждого ответа.
- [x] **Check Progress Node**:
    *   Управление переходом к следующему вопросу или завершением.
- [x] **Mentor Node**:
    *   Синтез итогового отчета на основе накопленной `quiz_history`.

### 2. Управление состоянием (QuizState)
- [x] Обновить `AgentState`: добавить `quiz_history`, `last_evaluation`.
- [x] Реализовать сохранение прослеживаемости (traceability) оценок.

### 3. Сборка графа
- [x] Определить `StateGraph` для Quiz.
- [x] Настроить ветвление: MCQ vs Open-ended.
- [x] Интегрировать `Shared Retrieval` для подсказок (Hints).

### 4. Тестирование
- [x] Создать комплексный тест: `agent_service/tests/scenarios/test_quiz_graph_comprehensive.py`.
- [x] Проверить 7 сценариев (MCQ, Open, Hint, Skip, Router, Mentor).

## Ожидаемый результат
Модуль `quiz.py` v3.5, обеспечивающий высокую точность роутинга и детальную историю обучения.