#!/bin/bash
# Фикс маршрутов AdGuard VPN для selective routing
# Запускать после каждого подключения VPN или по таймеру

# Ждем инициализации VPN
sleep 2

# Удаляем ВСЕ правила для таблицы 880
while ip rule del from all lookup 880 2>/dev/null; do :; done

# Удаляем возможные дубликаты правил для openrouter
while ip rule del from all to 104.18.2.115 lookup vpn 2>/dev/null; do :; done
while ip rule del from all to 104.18.3.115 lookup vpn 2>/dev/null; do :; done

# Добавляем точечные правила для openrouter (только один раз)
ip rule add from all to 104.18.2.115 lookup vpn
ip rule add from all to 104.18.3.115 lookup vpn

# Восстанавливаем маршрут в таблицу vpn
ip route replace default dev tun0 table vpn 2>/dev/null || true

# Очищаем кэш
ip route flush cache

# Логирование
logger "VPN routes fixed: removed 880, restored openrouter routing"

echo "✅ VPN routes fixed"
echo ""
echo "Проверка:"
echo "1. Правила (должно быть БЕЗ lookup 880):"
ip rule show | grep -E "(vpn|880)" || echo "   Нет правил vpn/880"
echo ""
echo "2. Маршрут для openrouter:"
ip route get 104.18.2.115
echo ""
echo "3. Таблица vpn:"
ip route show table vpn
