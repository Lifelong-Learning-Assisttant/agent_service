# Agent Service

Основной оркестратор системы Lifelong Learning Assistant. Реализует логику LLM-агента на базе LangGraph, управляет сессиями пользователей и интегрирует внешние инструменты (RAG, Test Generator).

## 🚀 Возможности

- **LangGraph Orchestration**: Управление сложными сценариями диалога (планирование, поиск, генерация).
- **Session Management**: Поддержка множественных параллельных сессий с изоляцией состояния.
- **Async Tools**: Асинхронное взаимодействие с внешними сервисами (RAG, Test Generator) для высокой производительности.
- **Real-time Feedback**: Отправка событий прогресса в Web UI через WebSocket.
- **Multi-Provider LLM**: Поддержка OpenAI, OpenRouter, Mistral, Z.ai.

## 📚 Документация

Вся детальная документация находится в папке [`docs/`](docs/):

- **[Общая документация агента](docs/agent_documentation.md)**: Архитектура, граф состояний, управление сессиями.
- **[Архитектура проекта](docs/project_architecture.md)**: Высокоуровневый обзор архитектуры.
- **[Сетевое взаимодействие](docs/network_interaction.md)**: Описание взаимодействия с другими сервисами.
- **[Развертывание в Docker](docs/docker_deployment.md)**: Инструкции по запуску в контейнерах.
- **[Тестирование](docs/test_documentation.md)**: Руководство по запуску тестов.

## 🛠 Быстрый старт

### Требования
- Python 3.12+
- Docker & Docker Compose (для интеграционных тестов)

### Локальный запуск (DEV)

1. **Настройка окружения**:
   ```bash
   cp .env_example .env
   # Заполните API ключи в .env
   ```

2. **Установка зависимостей**:
   ```bash
   uv sync
   ```

3. **Запуск сервера**:
   ```bash
   uv run python app.py --settings app_settings-dev.json
   ```
   Сервер запустится на порту `8250`.

## 🐳 Docker

Сервис запускается как часть общей системы через корневой `docker-compose-dev.yml` или `docker-compose-prod.yml`.

- **DEV порт**: `8250`
- **PROD порт**: `8270`

Подробнее см. в [инструкциях по развертыванию](../../docs/deployment/scripts.md).