# Документация по сетевому взаимодействию

Этот документ описывает сетевое взаимодействие между сервисом агента и веб-интерфейсом в средах разработки и продакшена.

## Обзор

Система состоит из двух основных сервисов:
- **Сервис агента**: Обрабатывает логику и взаимодействия, связанные с агентом.
- **Веб-интерфейс**: Предоставляет пользовательский интерфейс для взаимодействия с агентом.

Оба сервиса имеют отдельные конфигурации для сред разработки и продакшена, использующие изолированные Docker сети.

## Диаграмма сети

```mermaid
graph TD
    subgraph Среда разработки
        A1[Dev Agent Service<br/>Порт 8250] -->|web_ui_network_dev| B1[Dev Web UI Service<br/>Порт 8350]
        B1 -->|web_ui_network_dev| A1
    end

    subgraph Среда продакшена
        A2[Prod Agent Service<br/>Порт 8270] -->|web_ui_network_prod| B2[Prod Web UI Service<br/>Порт 8150]
        B2 -->|web_ui_network_prod| A2
    end

    subgraph Общие сервисы
        D[RAG Service<br/>Порт 8000] -->|bridge| A1
        D -->|bridge| A2
        E[Test Generator<br/>Порт 52812] -->|bridge| A1
        E -->|bridge| A2
    end
```

## Среда разработки

### Dev Agent Service
- **Порт**: 8250
- **Имя сервиса**: `agent_dev`
- **Сеть**: `web_ui_network_dev`
- **Конфигурация**: `app_settings-dev.json`
- **URL Web UI**: `http://web_ui_dev:8350`

### Dev Web UI Service
- **Порт**: 8350
- **Имя сервиса**: `web_ui_dev`
- **Сеть**: `web_ui_network_dev`
- **URL Agent Service**: `http://agent_dev:8250`

### Взаимодействие
- Сервис агента в среде разработки взаимодействует с веб-интерфейсом через сеть `web_ui_network_dev`.
- Веб-интерфейс в среде разработки взаимодействует с сервисом агента на порту 8250.

## Среда продакшена

### Prod Agent Service
- **Порт**: 8270
- **Имя сервиса**: `agent_prod`
- **Сеть**: `web_ui_network_prod`
- **Конфигурация**: `app_settings-prod.json`
- **URL Web UI**: `http://web_ui_prod:8150`

### Prod Web UI Service
- **Порт**: 8150
- **Имя сервиса**: `web_ui_prod`
- **Сеть**: `web_ui_network_prod`
- **URL Agent Service**: `http://agent_prod:8270`

### Взаимодействие
- Сервис агента в среде продакшена взаимодействует с веб-интерфейсом через сеть `web_ui_network_prod`.
- Веб-интерфейс в среде продакшена взаимодействует с сервисом агента на порту 8270.
- Оба сервиса находятся в сети `web_ui_network_prod`, что обеспечивает их изоляцию и корректное взаимодействие.

## Общие сервисы

Оба сервиса агента (dev и prod) взаимодействуют со следующими общими сервисами через сети Docker:

### RAG Service
- **Порт**: 8000
- **URL**: `http://rag-api:8000`
- **Сеть**: `rag_rag_network`
- **Используется для**: Retrieval-Augmented Generation

### Test Generator Service
- **Порт**: 52812
- **URL**: `http://api:52812` (в сети `test_generator_default`)
- **Сеть**: `test_generator_default`
- **Контейнер**: `llm-tester-api`
- **Используется для**: Генерация тестов и их оценка через async-инструменты

## Примечание о сетях

Dev и prod сервисы используют разные сети (`web_ui_network_dev` и `web_ui_network_prod` соответственно) для обеспечения изоляции и предотвращения конфликтов. Это позволяет:
- Избегать случайного взаимодействия между dev и prod сервисами.
- Обеспечивать предсказуемое разрешение имен сервисов внутри каждой сети.
- Упрощать управление и отладку, так как каждая среда изолирована.

## Порядок запуска сервисов

### Для Production
При запуске prod-сервисов важно соблюдать порядок:
1. **Сначала запустите `web_ui_service`**:
   ```bash
   cd web_ui_service
   docker compose -f docker-compose-prod.yml up -d
   ```
   Это создаст сеть `web_ui_network_prod`.

2. **Затем запустите `agent_service`**:
   ```bash
   cd agent_service
   docker compose -f docker-compose-prod.yml up -d
   ```
   Это подключит сервис агента к уже созданной сети `web_ui_network_prod`.

### Для Development
Для dev режима порядок не критичен, но рекомендуется:
1. **Сначала запустите `web_ui_service`**:
   ```bash
   cd web_ui_service
   docker compose -f docker-compose-dev.yml up -d
   ```

2. **Затем запустите `agent_service`**:
   ```bash
   cd agent_service
   docker compose -f docker-compose-dev.yml up --build -d
   ```

Этот порядок важен, так как `web_ui_service` создает сеть, к которой затем подключается `agent_service`.

## Настройка async-инструментов

Для работы async-инструментов с test_generator необходимо:

1. **Добавить httpx в зависимости** (уже в `pyproject.toml`):
   ```toml
   dependencies = [
       "httpx",
       ...
   ]
   ```

2. **Настроить переменные окружения**:
   - `TEST_GENERATOR_SERVICE_URL=http://api:52812`

3. **Обновить docker-compose файлы**:
   - Добавить сеть `test_generator_network` с внешней сетью `test_generator_default`
   - Убедиться, что контейнер agent_service подключен к этой сети

4. **Синхронизировать зависимости в контейнере**:
   ```bash
   docker exec agent_service-agent_dev-1 uv sync
   ```

## Итоги

- **Среда разработки**: Агент на порту 8250, Веб-интерфейс на порту 8350, сеть `web_ui_network_dev`
- **Среда продакшена**: Агент на порту 8270, Веб-интерфейс на порту 8150, сеть `web_ui_network_prod`
- **Общие сервисы**: Все сервисы используют те же порты для взаимодействия с RAG и Test Generator
- **Изоляция**: Разные сети для dev и prod предотвращают конфликты
- **Async-инструменты**: Работают через httpx с test_generator по адресу `http://api:52812` в сети `test_generator_default`

Эта конфигурация обеспечивает возможность одновременной работы обеих сред без конфликтов портов, сохраняя при этом согласованное взаимодействие с общими сервисами.