# AdGuard VPN + OpenRouter: Selective Routing

## Проблема

### Географические ограничения
OpenRouter блокирует доступ из российских IP-адресов:
```
Error code: 403 - {'error': {'message': 'Access denied: This service is not available in your region.'}}
```

### Дилемма
- **VPN для всего трафика**: ❌ Ломает доступ к локальным сервисам в РФ
- **Без VPN**: ❌ OpenRouter недоступен
- **Решение**: ✅ Селективный VPN (только openrouter.ai)

## Решение

Скрипт [`fix-vpn-routes.sh`](../fix-vpn-routes.sh) автоматически настраивает селективную маршрутизацию:
- ✅ OpenRouter идет через VPN
- ✅ Локальные сервисы работают напрямую
- ✅ Остальной интернет без VPN

### Предварительная настройка

Перед использованием скрипта необходимо настроить AdGuard VPN CLI в режиме selective:
```bash
# Установить режим selective
adguardvpn-cli site-exclusions mode selective

# Добавить домены OpenRouter
adguardvpn-cli site-exclusions add openrouter.ai
adguardvpn-cli site-exclusions add api.openrouter.ai

# Подключить VPN
adguardvpn-cli connect -l de
```

Подробная инструкция: [adguard_vpn_setup.md](./adguard_vpn_setup.md)

## Быстрое использование

```bash
# После подключения VPN запустите скрипт
sudo ./agent_service/fix-vpn-routes.sh
```

Скрипт автоматически:
1. Определит VPN интерфейс
2. Получит текущие IP-адреса OpenRouter
3. Удалит избыточные правила
4. Добавит точечные маршруты для OpenRouter
5. Проверит работоспособность

## Проверка после запуска

```bash
# 1. Правила для OpenRouter (должны быть через lookup vpn)
ip rule show | grep -E "104.18|2606:4700"

# 2. Маршрут к OpenRouter (должен идти через VPN)
ip route get 104.18.2.115

# 3. Таблица vpn (должна содержать маршруты)
ip route show table vpn

# 4. Тест доступности
curl -I https://openrouter.ai
```

**Нормальное состояние:**
- `ip rule show` → НЕТ правила `lookup 880`, ЕСТЬ правила `104.18.x.x lookup vpn`
- `ip route get 104.18.2.115` → `dev tun0 table vpn`
- `ip route show table vpn` → `default dev tun0 scope link`
- `curl` → HTTP 200

## Автоматизация

### Вариант 1: Ручной запуск после каждого подключения

```bash
adguardvpn-cli connect
sleep 3
sudo ./agent_service/fix-vpn-routes.sh
```

### Вариант 2: Systemd timer (рекомендуется)

Создайте два файла:

**`/etc/systemd/system/fix-vpn-routes.service`:**
```ini
[Unit]
Description=Fix VPN routes after reconnect
After=network.target

[Service]
Type=oneshot
ExecStart=/path/to/project/agent_service/fix-vpn-routes.sh
User=root
```

**`/etc/systemd/system/fix-vpn-routes.timer`:**
```ini
[Unit]
Description=Check VPN routes every 5 minutes
Requires=fix-vpn-routes.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

**Включение:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fix-vpn-routes.timer
```

### Вариант 3: Cron job

```bash
sudo crontab -e
```

Добавить строку:
```bash
*/5 * * * * /path/to/project/agent_service/fix-vpn-routes.sh
```

## Диагностика проблем

### Проблема: Локальные сервисы недоступны

**Причина**: Правило `lookup 880` перехватывает весь трафик.

**Решение**:
```bash
# Проверить наличие правила
ip rule list | grep 880

# Если есть - запустить исправление
sudo ./agent_service/fix-vpn-routes.sh
```

### Проблема: OpenRouter недоступен

**Причина**: VPN не подключен или маршруты не настроены.

**Решение**:
```bash
# 1. Проверить VPN статус
adguardvpn-cli status

# 2. Проверить маршруты
ip route get 104.18.2.115

# 3. Проверить исключения
adguardvpn-cli site-exclusions show

# 4. Запустить исправление
sudo ./agent_service/fix-vpn-routes.sh
```

### Проблема: DNS не работает

**Причина**: Проблемы с DNS-серверами.

**Решение**:
```bash
# Проверить DNS
nslookup openrouter.ai
nslookup google.com

# Проверить /etc/resolv.conf
cat /etc/resolv.conf
```

## Что делает скрипт

Скрипт [`fix-vpn-routes.sh`](../fix-vpn-routes.sh) выполняет следующие действия:

1. **Проверяет подключение VPN**
   - Проверяет наличие таблицы 880 с маршрутами через tun0
   - Если VPN не подключен - сообщает об ошибке

2. **Определяет VPN интерфейс**
   - Автоматически находит имя tun интерфейса
   - Поддерживает разные версии VPN клиента

3. **Получает IP-адреса OpenRouter**
   - Динамически определяет через DNS: `dig` или `nslookup`
   - Поддерживает IPv4 и IPv6 адреса

4. **Удаляет избыточные правила**
   - Удаляет правило `lookup 880` (которое перехватывает ВЕСЬ трафик)
   - Удаляет возможные дубликаты правил для OpenRouter

5. **Добавляет точечные маршруты**
   - Только IP-адреса OpenRouter идут через VPN
   - Остальной трафик работает напрямую

6. **Восстанавливает таблицу vpn**
   - Добавляет `default dev tun0 scope link` в таблицу `vpn`

7. **Очищает кэш маршрутов**
   - `ip route flush cache`

8. **Проверяет работоспособность**
   - Проверяет маршруты
   - Тестирует доступность OpenRouter
   - Показывает результат

## Root cause

AdGuard VPN в режиме selective работает так:
- Добавляет правило `lookup 880` для перехвата трафика
- Добавляет маршруты в таблицу `vpn`
- **Проблема**: Правило `lookup 880` слишком общее и перехватывает ВЕСЬ трафик

Скрипт исправляет это, удаляя общее правило и добавляя точечные маршруты только для OpenRouter.

## См. также

- [Настройка AdGuard VPN CLI](./adguard_vpn_setup.md) - Полная настройка VPN
- [Сетевая архитектура](./network_architecture.md) - Общая схема работы
- [Скрипт исправления](../fix-vpn-routes.sh) - Исходный код скрипта
