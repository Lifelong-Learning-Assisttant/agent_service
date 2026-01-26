# Планирование покрытия тестами (Quiz Subgraph)

## Цель
Обеспечить 100% покрытие логических веток в `agent_service/graphs/quiz.py` модульными тестами.

## Узлы и Ветки (Nodes & Branches)

### 1. `quiz_router_node` (Маршрутизация)
- [ ] **CLI Command: Skip**: Ввод `/skip_question` -> intent `skip_question`.
- [ ] **CLI Command: Finish**: Ввод `/finish_quizz` -> intent `evaluate_quiz`.
- [ ] **Intent: Answer**: Обычный ответ на вопрос -> intent `quiz_answering`.
- [ ] **Intent: Skip**: "Пропусти", "Не знаю" -> intent `skip_question`.
- [ ] **Intent: Help**: "Подскажи", "Намекни" -> intent `quiz_answering` (но с пометкой для interviewer).
- [ ] **Intent: Stop**: "Хватит", "Стоп" -> intent `evaluate_quiz`.
- [ ] **Intent: Search**: "Что такое X (не по теме)?" -> intent `rag_answer`.
- [ ] **Pre-set Intent**: Если `state.intent` уже установлен -> сохранить его.

### 2. `interviewer_node` (Интервьюер)
- [ ] **Answer Processing**: Обычный ответ -> добавить в `user_answers`.
- [ ] **Hint Request**: Пришли с `documents` (после RAG) -> сгенерировать подсказку (`final_answer`), не сохранять ответ как решение.

### 3. `skip_node` (Пропуск)
- [ ] **Skip Action**: Добавить `[SYSTEM: SKIPPED]` в `user_answers`.

### 4. `check_progress_node` (Проверка прогресса)
- [ ] **Next Question**: Есть следующий вопрос -> обновить `current_quiz_index`, вернуть `NEXT_QUESTION`.
- [ ] **Finished**: Вопросы кончились -> intent `evaluate_quiz`.

### 5. `mentor_node` (Ментор)
- [ ] **Evaluation**: Квиз только завершился (`quiz_questions` не пуст) -> оценка, фидбек, очистка вопросов.
- [ ] **Discussion**: Квиз уже завершен (`quiz_questions` пуст) -> обсуждение результатов.

### 6. `route_quiz` (Conditional Edge)
- [ ] **skip_question** -> `skip`
- [ ] **evaluate_quiz** -> `mentor`
- [ ] **rag_answer** -> `search` (retrieval)
- [ ] **quiz_answering** -> `interviewer`

### 7. `route_post_interviewer` (Conditional Edge)
- [ ] **Hint Given** (`final_answer` exists) -> `end` (ждем ввода пользователя).
- [ ] **Answer Processed** -> `check_progress`.

### 8. `route_post_check` (Conditional Edge)
- [ ] **More Questions** -> `interviewer` (на самом деле END, т.к. вопрос уже в `final_answer`).
- [ ] **Finished** (`evaluate_quiz`) -> `mentor`.

## План реализации тестов

Создать файл `agent_service/tests/scenarios/test_quiz_graph_comprehensive.py` со следующими сценариями:

1.  `test_quiz_router_cli_commands`: Проверка `/skip_question` и `/finish_quizz`.
2.  `test_quiz_router_llm_intents`: Проверка классификации LLM (answer, skip, help, stop, search).
3.  `test_interviewer_answer`: Проверка сохранения ответа пользователя.
4.  `test_interviewer_hint`: Проверка генерации подсказки при наличии документов.
5.  `test_skip_logic`: Проверка добавления системного маркера пропуска.
6.  `test_progress_next`: Переход к следующему вопросу.
7.  `test_progress_finish`: Завершение квиза при достижении конца списка.
8.  `test_mentor_evaluation`: Генерация фидбека при завершении.
9.  `test_mentor_discussion`: Обсуждение после завершения (пустой список вопросов).
10. `test_rag_search_flow`: Сценарий "Вопрос -> Search -> Hint -> Answer".

## Инструменты
Использовать `langgraph` методы проверки графа или моки для изоляции узлов.