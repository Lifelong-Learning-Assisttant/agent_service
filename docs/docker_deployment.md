# Docker Deployment Guide

Этот документ описывает систему развертывания agent_service с использованием Docker для разработки и продакшена.

## Структура файлов

```
agent_service/
├── app_settings-dev.json      # Конфиг для разработки (порт 8350, is_dev_version: true)
├── app_settings-prod.json     # Конфиг для продакшена (порт 8150, is_dev_version: false)
├── Dockerfile-dev             # Dockerfile для разработки
├── Dockerfile-prod            # Dockerfile для продакшена
├── docker-compose-dev.yml     # Docker Compose для разработки (agent_dev)
├── docker-compose-prod.yml    # Docker Compose для продакшена (agent_prod)
├── agent_system.py            # Основной код (поддерживает --settings, показывает индикатор dev)
├── app.py                     # API сервер (поддерживает --settings)
└── docs/
    └── docker_deployment.md  # Эта документация
```

## Индикатор версии

В логах и API ответах отображается индикатор версии:
- **Dev версия**: Показывает в логах "⚠️ Это dev версия агента"
- **Prod версия**: Без индикатора

Это помогает визуально отличить среды при одновременной работе.

## Режим разработки (Development)

### Назначение
- Быстрая разработка с горячей перезагрузкой кода
- Изменения в коде отражаются автоматически без пересборки контейнера
- Используется для отладки и тестирования новых функций

### Как использовать

1. **Запуск сервиса:**
   ```bash
   cd agent_service
   docker-compose -f docker-compose-dev.yml up --build
   ```

2. **Особенности:**
   - Порт: 8350
   - Имя сервиса: `agent_dev`
   - Код монтируется через volume: `./:/app`
   - Изменения в файлах `.py` сразу отражаются в контейнере
   - Использует `app_settings-dev.json`
   - Команда запуска: `uv run python app.py --settings app_settings-dev.json`

3. **Остановка:**
   ```bash
   docker-compose -f docker-compose-dev.yml down
   ```

### Технические детали

**Dockerfile-dev:**
- Минимальный образ Python 3.13-slim
- Устанавливает только uv и зависимости
- НЕ копирует код приложения
- Код монтируется при запуске через volume

**docker-compose-dev.yml:**
```yaml
services:
  agent_dev:              # Уникальное имя сервиса
    build:
      context: .
      dockerfile: Dockerfile-dev
    ports:
      - "8350:8350"
    volumes:
      - .:/app              # Монтирование кода
      - /app/__pycache__    # Исключение кэша
      - /app/.pytest_cache  # Исключение кэша тестов
    environment:
      - ADDITION_SERVICE_URL=http://addition_service:8000
      - RAG_SERVICE_URL=http://rag-api:8000
    command: uv run python app.py --settings app_settings-dev.json
    networks:
      - default
      - rag_network
      - test_generator_network
      - web_ui_network
```

## Режим продакшена (Production)

### Назначение
- Стабильная версия сервиса для развертывания
- Использует заранее собранный Docker образ
- Подходит для CI/CD и production сред

### Как использовать

1. **Сборка образа:**
   ```bash
   cd agent_service
   docker build -f Dockerfile-prod -t agent_service:v001 .
   ```

2. **Запуск сервиса:**
   ```bash
   docker-compose -f docker-compose-prod.yml up
   ```

3. **Особенности:**
   - Порт: 8150
   - Имя сервиса: `agent_prod`
   - Код ВКЛЮЧЕН в образ (скопирован при сборке)
   - Монтируется ТОЛЬКО конфиг: `./app_settings-prod.json:/app/app_settings.json:ro`
   - Использует `app_settings-prod.json`
   - Команда запуска: `uv run python app.py --settings app_settings.json`

### Технические детали

**Dockerfile-prod:**
- Полный образ с кодом приложения
- Копирует весь код: `COPY . .`
- Использует `app_settings.json` внутри контейнера (переопределяется через volume)

**docker-compose-prod.yml:**
```yaml
services:
  agent_prod:             # Уникальное имя сервиса
    image: agent_service:latest  # Использует готовый образ
    ports:
      - "8150:8150"
    volumes:
      - ./app_settings-prod.json:/app/app_settings.json:ro  # Только конфиг
    environment:
      - ADDITION_SERVICE_URL=http://addition_service:8000
      - RAG_SERVICE_URL=http://rag-api:8000
    command: uv run python app.py --settings app_settings.json
    networks:
      - default
      - rag_network
      - test_generator_network
      - web_ui_network
```

## Публикация в GitHub Container Registry

Для публикации образа в GitHub Container Registry (GHCR):

```bash
# Логин в GHCR
docker login ghcr.io/your-username

# Сборка и тегирование
docker build -f Dockerfile-prod -t ghcr.io/your-username/agent_service:v001 .
docker push ghcr.io/your-username/agent_service:v001

# Запуск из GHCR
docker pull ghcr.io/your-username/agent_service:v001
docker-compose -f docker-compose-prod.yml up
```

### Релизная версия

В настоящее время доступна релизная версия Docker-образа:

```bash
docker pull ghcr.io/lifelong-learning-assisttant/agent_service:v001
```

Этот образ предназначен для использования в составе общей системы lifelong_learning_assistant. Для разработки и внесения изменений используйте development режим, описанный выше.

## Сравнение режимов

| Аспект | Development | Production |
|--------|-------------|------------|
| **Порт** | 8350 | 8150 |
| **Код** | Volume (изменения实时) | Внутри образа |
| **Конфиг** | app_settings-dev.json | app_settings-prod.json |
| **Сборка** | При каждом запуске | Один раз |
| **Скорость** | Быстрые изменения | Стабильность |
| **Назначение** | Разработка | Продакшен |

## Переменные окружения

Оба режима используют:
- `PYTHONUNBUFFERED=1` - немедленный вывод логов
- `ADDITION_SERVICE_URL=http://addition_service:8000` - URL сервиса сложения
- `RAG_SERVICE_URL=http://rag-api:8000` - URL RAG сервиса

## Проверка работы

### Development
```bash
# Запуск
cd agent_service
docker-compose -f docker-compose-dev.yml up --build

# Проверить логи
docker-compose -f docker-compose-dev.yml logs -f

# Проверить порт
curl http://localhost:8350/health

# Проверить контейнеры
docker-compose -f docker-compose-dev.yml ps

# Остановка
docker-compose -f docker-compose-dev.yml down
```

### Production
```bash
# Сборка образа
cd agent_service
docker build -f Dockerfile-prod -t agent_service:v001 .

# Запуск
docker-compose -f docker-compose-prod.yml up

# Проверить логи
docker-compose -f docker-compose-prod.yml logs -f

# Проверить порт
curl http://localhost:8150/health

# Проверить контейнеры
docker-compose -f docker-compose-prod.yml ps

# Остановка
docker-compose -f docker-compose-prod.yml down
```

### Запуск обоих окружений одновременно
```bash
# Terminal 1 - Development
cd agent_service
docker-compose -f docker-compose-dev.yml up --build

# Terminal 2 - Production
cd agent_service
docker-compose -f docker-compose-prod.yml up
```

Контейнеры будут называться:
- `agent_dev_1` (dev, порт 8350)
- `agent_prod_1` (prod, порт 8150)

## Отладка

### Проблемы с development
1. **Изменения не отражаются:**
   - Проверьте права доступа к файлам
   - Убедитесь, что файлы в текущей директории
   - Перезапустите контейнер

2. **Порт занят:**
   - Измените порт в docker-compose-dev.yml и app_settings-dev.json

### Проблемы с production
1. **Образ не найден:**
   - Убедитесь, что образ собран: `docker images | grep agent_service`

2. **Ошибка конфигурации:**
   - Проверьте путь к app_settings-prod.json
   - Убедитесь, что файл существует и читаем

## Взаимодействие с Web UI

Dev агент общается с dev Web UI на порту 8350:
- Web UI dev: http://localhost:8350
- Agent dev: http://localhost:8350

Prod агент общается с prod Web UI на порту 8150:
- Web UI prod: http://localhost:8150
- Agent prod: http://localhost:8150

Оба агента общаются с остальными сервисами (addition_service, rag-api, test_generator) по тем же портам, что и раньше.