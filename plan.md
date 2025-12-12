Проблема заключается в **критической логической ошибке в файле `app.py`**, из-за которой ваше приложение отправляет не один запрос, а **сотни запросов** (по одному на каждую букву сообщения), что моментально вызывает блокировку (Rate Limit) со стороны OpenRouter и бесконечные циклы повторных попыток (retries), которые выглядят как зависание.

Вот подробный разбор и решение.

### 1\. Корневая причина: Ошибка передачи данных (String vs List)

В `llm_client.py` метод `generate` ожидает **список** строк (`Sequence[str]`), но в `app.py` вы передаете ему одну **строку**. В Python строка является последовательностью символов.

**Как работает ваш код сейчас:**

1.  Вы отправляете сообщение: `"Привет"`.
2.  `app.py` вызывает `LLM_CLIENT.generate("Привет")`.
3.  В `llm_client.py` цикл `for idx, t in enumerate(texts, 1):` начинает перебирать переданный аргумент.
4.  Так как аргумент — строка, он перебирает её по буквам:
      * Запрос 1: промпт `"П"`
      * Запрос 2: промпт `"р"`
      * Запрос 3: промпт `"и"`
      * ... и т.д.

**Почему это вызывает таймаут:**
Вы совершаете D-DoS атаку на свой же API-ключ. OpenRouter (или любой другой провайдер) моментально возвращает ошибку **429 Too Many Requests** после первых нескольких букв. Ваш `llm_client.py` имеет встроенную логику **Retry** (повторных попыток) с ожиданием (`time.sleep`), которая перехватывает 429 ошибку и ждет. В итоге приложение "виснет", пытаясь отправить сотни запросов и постоянно ожидая разблокировки.

-----

### 2\. Решение

Вам нужно исправить вызов метода в файле `app.py`. Оберните сообщение в список `[...]`, и заберите первый элемент результата `[0]`.

#### Файл: `app.py`

**Было (с ошибкой):**

```python
    # ...
    if payload.provider and payload.provider != settings.default_provider:
        local_client = LLMClient(provider=payload.provider)
        answer = local_client.generate(payload.message) # <-- ОШИБКА ЗДЕСЬ
    else:
        answer = LLM_CLIENT.generate(payload.message)   # <-- И ЗДЕСЬ

    return MessageOut(answer=answer)
```

**Стало (Исправлено):**

```python
    # ...
    if payload.provider and payload.provider != settings.default_provider:
        local_client = LLMClient(provider=payload.provider)
        # Передаем список и берем первый элемент результата
        results = local_client.generate([payload.message])
        answer = results[0] if results else ""
    else:
        # Передаем список и берем первый элемент результата
        results = LLM_CLIENT.generate([payload.message])
        answer = results[0] if results else ""

    return MessageOut(answer=answer)
```

-----

### 3\. Дополнительная рекомендация: Синхронизация моделей

Ваши скрипты работают быстро еще и потому, что используют конкретную легкую модель, а приложение использует `openrouter/auto` (настройка по умолчанию в `settings.py`), которая может выбирать более тяжелые или перегруженные модели.

Для чистоты эксперимента приведите `.env` вашего приложения к тем же настройкам, что и в успешном тесте.

**В файле `.env`:**

```bash
# Убедитесь, что провайдер переключен на openrouter
LLM_DEFAULT_PROVIDER=openrouter

# Используйте ту же модель, что и в успешном тесте (test_openrouter.py)
LLM_OPENROUTER_CHAT_MODEL=kwaipilot/kat-coder-pro:free
```

### Итог

Главная проблема — **итерация по строке вместо списка** в `app.py`. Исправьте `generate(payload.message)` на `generate([payload.message])[0]`, и зависания исчезнут.