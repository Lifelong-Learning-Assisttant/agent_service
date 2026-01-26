# Этап 1: Shared Retrieval Subgraph (Отчет о прогрессе)

## 🎯 Цель
Реализовать унифицированный подграф поиска (`Shared Retrieval Subgraph`), описанный в [архитектурной документации](agent_service/docs/agent_documentation.md). Подграф должен служить единым источником знаний для всех режимов (Chat, Quiz, Algo), уметь маршрутизировать запросы к RAG, Tavily и Context7, агрегировать результаты и синтезировать финальный учебный материал.

## Статус: ✅ Завершено (100%)

## ✅ Что было сделано:

### 1. Инфраструктура и Состояние
- Создана директория [`agent_service/graphs/`](agent_service/graphs/) и [`agent_service/state.py`](agent_service/state.py).
- В `state.py` определены:
    - `AgentState`: Базовое состояние.
    - `RetrievalState`: Состояние поиска. **Важно**: Поле `raw_results` использует `Annotated[Dict[str, Any], operator.ior]` для корректного слияния данных из параллельных веток графа.

### 2. Инструменты (Smart Tools)
- Создан модуль [`agent_service/retrieval_langchain_tools.py`](agent_service/retrieval_langchain_tools.py).
- Реализован **Smart Library Resolver**:
    - Сначала проверяет `ML_LIBRARIES_MAP` (хардкод для PyTorch, Sklearn и др.).
    - Затем использует **Context7 API v2** (`/libs/search`) для динамического поиска `libraryId`.
- Инструмент `context7_docs_async` переведен на **API v2** (`/context?type=json`):
    - Корректно парсит `codeSnippets` и `infoSnippets`.
    - Возвращает унифицированный список документов.
- Добавлен `rag_generate_async` для прямой генерации из RAG (используется в некоторых сценариях).

### 3. Реализация Подграфа ([`agent_service/graphs/retrieval.py`](agent_service/graphs/retrieval.py))
- **Nodes**: `router`, `rag`, `web`, `resolver`, `docs`, `aggregator`, `prepare_material`.
- **Логика**:
    - Роутер выбирает источники.
    - Если выбраны `docs`, управление идет в `resolver`, затем в `docs`.
    - `aggregator` собирает результаты (добавлена фильтрация по `selected_sources`).
    - `prepare_material` синтезирует финальный Markdown.

### 4. Интеграция и Слияние
- Ветка `version_2` (безопасность Docker, обновления User Service) успешно влита в `subgraph_agent`.
- Конфликты в `settings.py` разрешены:
    - Ключи `TAVILY_API_KEY` и `CONTEXT7_API_KEY` теперь имеют алиасы.
    - Убран префикс `LLM_` из `SettingsConfigDict` для корректного чтения `.env`.
- Сабмодули обновлены до последних версий.

### 5. Тестирование
- Созданы модульные тесты в `agent_service/tests/scenarios/`:
    - `test_retrieval_rag.py`
    - `test_retrieval_tavily.py`
    - `test_retrieval_context7_mapped.py`
    - `test_retrieval_context7_dynamic.py`
    - `test_retrieval_mixed.py`
    - `test_retrieval_smart_choice.py` (свободный выбор агента).

---

## 🚧 Текущее состояние и проблемы:
- Ошибки импорта и связности устранены.
- Подтверждена стабильная работа при использовании глобальных скриптов запуска (`start-dev.sh`).

---

## 📋 План для следующего инстанса:
1. **Приступить к Stage 2 (Chat Subgraph)**.