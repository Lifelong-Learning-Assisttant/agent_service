# Проблема с доступом к RAG-сервису из контейнера Docker

## Описание проблемы

При попытке доступа к RAG-сервису из контейнера `agent_service` возникают ошибки подключения. Сервис RAG успешно запущен и доступен по адресу `http://localhost:8000` на хост-машине, однако внутри контейнера доступ к этому сервису невозможен.

## Предпринятые шаги по диагностике и устранению неполадок

### 1. Проверка доступности RAG-сервиса на хост-машине

Сервис RAG успешно отвечает на запросы с хост-машины:

```bash
curl -X 'POST' 'http://localhost:8000/search' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{"query": "тестирование", "top_k": 2, "use_hyde": false}'
```

Ответ сервиса:
```json
{
  "query": "тестирование",
  "documents": [...],
  "total_tokens": 2487,
  "num_documents": 2,
  "sources": [...],
  "used_hyde": false
}
```

### 2. Попытка доступа из контейнера `agent_service`

При запуске тестов внутри контейнера:

```bash
docker exec -it agent_service uv run python test_rag_tools.py
```

Получаем ошибки:
- **Ошибка 1:** `Connection refused` при использовании `http://localhost:8000`
- **Ошибка 2:** `Name or service not known` при использовании `http://host.docker.internal:8000`

### 3. Изменение конфигурации URL в `app_settings.json`

Были предприняты следующие изменения:

1. **Использование `localhost`:**
   ```json
   "rag_service_url": "http://localhost:8000"
   ```
   Результат: `Connection refused`

2. **Использование `host.docker.internal`:**
   ```json
   "rag_service_url": "http://host.docker.internal:8000"
   ```
   Результат: `Name or service not known`

3. **Использование IP-адреса шлюза Docker (`172.17.0.1`):**
   ```json
   "rag_service_url": "http://172.17.0.1:8000"
   ```
   Результат: Ожидается проверка

## Анализ проблемы

### Почему стандартные методы не работают?

1. **`localhost` внутри контейнера:**
   Внутри контейнера `localhost` указывает на сам контейнер, а не на хост-машину. Это стандартное поведение Docker, и поэтому сервис, запущенный на хост-машине, недоступен по этому адресу.

2. **`host.docker.internal`:**
   Это специальное DNS-имя, которое должно разрешаться в IP-адрес хост-машины. Однако оно может не работать по следующим причинам:
   - Docker не настроен для использования этого имени.
   - Версия Docker не поддерживает это имя по умолчанию.
   - Отсутствие соответствующих настроек в `/etc/hosts` внутри контейнера.

3. **IP-адрес шлюза (`172.17.0.1`):**
   Этот адрес является шлюзом по умолчанию для контейнеров Docker. Однако он может не работать, если:
   - Сервис RAG не прослушивает все интерфейсы (`0.0.0.0`).
   - На хост-машине включен фаервол, блокирующий доступ.
   - Сетевые политики Docker ограничивают доступ к хост-машине.

## Возможные решения

### 1. Настройка Docker для использования `host.docker.internal`

Добавить настройку в Docker:

```bash
docker run --add-host=host.docker.internal:host-gateway ...
```

Или обновить конфигурацию Docker для автоматического добавления этого хоста.

### 2. Использование IP-адреса хост-машины

Узнать IP-адрес хост-машины и использовать его в конфигурации:

```bash
ip addr show docker0
```

Затем обновить `app_settings.json`:

```json
"rag_service_url": "http://<HOST_IP>:8000"
```

### 3. Настройка сети Docker

Создать пользовательскую сеть Docker и подключить к ней оба контейнера:

```bash
docker network create my_network
docker run --network=my_network --name=rag_service ...
docker run --network=my_network --name=agent_service ...
```

### 4. Проверка конфигурации RAG-сервиса

Убедиться, что RAG-сервис прослушивает все интерфейсы:

```python
# В коде RAG-сервиса
app.run(host="0.0.0.0", port=8000)
```

### 5. Проверка фаервола

Убедиться, что фаервол на хост-машине не блокирует доступ:

```bash
sudo ufw allow 8000
```

## Заключение

Проблема связана с изоляцией сетевого окружения Docker. Для её решения необходимо либо настроить Docker для корректного разрешения имени хост-машины, либо использовать IP-адрес хост-машины, либо создать пользовательскую сеть Docker. Также важно убедиться, что RAG-сервис прослушивает все интерфейсы и нет блокировок со стороны фаервола.

## Дополнительные материалы

- [Docker Networking Documentation](https://docs.docker.com/network/)
- [Docker host.docker.internal](https://docs.docker.com/desktop/networking/#i-want-to-connect-from-a-container-to-a-service-on-the-host)
- [Docker Networking Best Practices](https://docs.docker.com/network/network-tutorial-standalone/)
