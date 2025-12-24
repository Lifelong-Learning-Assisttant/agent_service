# AdGuard VPN + OpenRouter: Selective Routing

## Проблема
AdGuard VPN при переподключении добавляет правило `lookup 880`, которое заставывает ВЕСЬ трафик идти через VPN. Это ломает локальные сервисы на сервере.

## Решение
Используйте скрипт [`fix-vpn-routes.sh`](./fix-vpn-routes.sh) для автоматического исправления маршрутов.

**Важно**: Перед использованием скрипта необходимо настроить AdGuard VPN CLI в режиме selective. Подробная инструкция: [adguard_vpn_setup.md](./adguard_vpn_setup.md)

## Быстрое использование

```bash
# Запустить скрипт после подключения VPN
sudo ./agent_service/fix-vpn-routes.sh
```

## Проверка после запуска

```bash
# 1. Правила (должно быть БЕЗ lookup 880)
ip rule show

# 2. Маршрут openrouter (должен быть table vpn)
ip route get 104.18.2.115

# 3. Таблица vpn (должна быть не пустой)
ip route show table vpn
```

**Нормальное состояние:**
- `ip rule show` → НЕТ правила `lookup 880`
- `ip route get 104.18.2.115` → `dev tun0 table vpn`
- `ip route show table vpn` → `default dev tun0 scope link`

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

Скрипт `fix-vpn-routes.sh` выполняет следующие действия:

1. **Удаляет правило `lookup 880`** (если есть)
   - Это правило перехватывает ВЕСЬ трафик и отправляет его через VPN
   - После удаления локальные сервисы снова работают

2. **Удаляет дублирующиеся правила**
   - Проверяет и удаляет все правила для таблицы `vpn`

3. **Добавляет точечные маршруты**
   - `104.18.2.115 dev tun0 scope link`
   - `104.18.3.115 dev tun0 scope link`
   - Только эти IP идут через VPN

4. **Восстанавливает маршруты из таблицы `vpn`**
   - Добавляет `default dev tun0 scope link` в таблицу `vpn`

5. **Очищает кэш маршрутов**
   - `ip route flush cache`

## Root cause

AdGuard VPN в режиме selective работает так:
- Добавляет правило `lookup 880` для перехвата трафика
- Добавляет маршруты в таблицу `vpn`
- **Проблема**: Правило `lookup 880` слишком общее и перехватывает ВЕСЬ трафик

Скрипт исправляет это, удаляя общее правило и добавляя точечные маршруты.

## См. также

- [Настройка AdGuard VPN CLI](./adguard_vpn_setup.md) - Полная настройка VPN
- [Сетевая архитектура](./network_architecture.md) - Общая схема работы
- [Скрипт исправления](../fix-vpn-routes.sh) - Исходный код скрипта
