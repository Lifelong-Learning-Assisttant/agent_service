#!/bin/bash
# Фикс маршрутов AdGuard VPN для selective routing
# Динамически определяет IP-адреса OpenRouter и OpenAI и добавляет только их в VPN

set -e

echo "=== Настройка селективного VPN для OpenRouter и OpenAI ==="
echo ""

# Проверяем, что VPN подключен (есть tun интерфейс и таблица 880)
if ! ip route show table 880 | grep -q "dev tun"; then
    echo "❌ VPN не подключен или таблица 880 пустая"
    echo "Сначала подключите VPN: adguardvpn-cli connect"
    exit 1
fi

# Определяем VPN интерфейс из таблицы 880
VPN_IFACE=$(ip route show table 880 | head -1 | awk '{print $3}')
if [ -z "$VPN_IFACE" ]; then
    VPN_IFACE="tun0"
fi
echo "✅ VPN интерфейс: $VPN_IFACE"

# Получаем текущие IP-адреса OpenRouter
echo "🔍 Получаем IP-адреса openrouter.ai..."
OPENROUTER_IPS=$(dig +short openrouter.ai A 2>/dev/null || nslookup openrouter.ai 2>/dev/null | grep "Address:" | grep -v "#53" | awk '{print $2}' | sort -u)

if [ -z "$OPENROUTER_IPS" ]; then
    echo "⚠️ Не удалось получить IP-адреса OpenRouter (возможно, DNS не работает)"
    OPENROUTER_IPS=""
else
    echo "✅ Найдены IP-адреса OpenRouter:"
    echo "$OPENROUTER_IPS" | while read ip; do
        echo "   - $ip"
    done
fi

# Получаем текущие IP-адреса OpenAI
echo "🔍 Получаем IP-адреса api.openai.com..."
OPENAI_IPS=$(dig +short api.openai.com A 2>/dev/null || nslookup api.openai.com 2>/dev/null | grep "Address:" | grep -v "#53" | awk '{print $2}' | sort -u)

if [ -z "$OPENAI_IPS" ]; then
    echo "⚠️ Не удалось получить IP-адреса OpenAI (возможно, DNS не работает)"
    OPENAI_IPS=""
else
    echo "✅ Найдены IP-адреса OpenAI:"
    echo "$OPENAI_IPS" | while read ip; do
        echo "   - $ip"
    done
fi

# Проверяем, есть ли вообще IP-адреса
if [ -z "$OPENROUTER_IPS" ] && [ -z "$OPENAI_IPS" ]; then
    echo "❌ Не удалось получить IP-адреса ни для одного сервиса"
    echo "Проверьте DNS: nslookup openrouter.ai и nslookup api.openai.com"
    exit 1
fi

# Удаляем старые правила lookup 880 (если есть)
echo ""
echo "🧹 Очищаем старые правила..."
while ip rule del from all lookup 880 2>/dev/null; do :; done

# Удаляем возможные дубликаты правил для OpenRouter и OpenAI
while ip rule del from all to 104.18.2.115 lookup vpn 2>/dev/null; do :; done
while ip rule del from all to 104.18.3.115 lookup vpn 2>/dev/null; do :; done
while ip rule del from all to 2606:4700::6812:273 lookup vpn 2>/dev/null; do :; done
while ip rule del from all to 2606:4700::6812:373 lookup vpn 2>/dev/null; do :; done

# Добавляем правила для текущих IP-адресов OpenRouter
if [ -n "$OPENROUTER_IPS" ]; then
    echo ""
    echo "➕ Добавляем маршруты для OpenRouter..."
    echo "$OPENROUTER_IPS" | while read ip; do
        if [ -n "$ip" ]; then
            # Проверяем, это IPv4 или IPv6
            if [[ $ip =~ : ]]; then
                # IPv6
                ip rule add from all to $ip lookup vpn 2>/dev/null && echo "   ✅ IPv6: $ip" || echo "   ⚠️ IPv6 уже существует: $ip"
            else
                # IPv4
                ip rule add from all to $ip lookup vpn 2>/dev/null && echo "   ✅ IPv4: $ip" || echo "   ⚠️ IPv4 уже существует: $ip"
            fi
        fi
    done
fi

# Добавляем правила для текущих IP-адресов OpenAI
if [ -n "$OPENAI_IPS" ]; then
    echo ""
    echo "➕ Добавляем маршруты для OpenAI..."
    echo "$OPENAI_IPS" | while read ip; do
        if [ -n "$ip" ]; then
            # Проверяем, это IPv4 или IPv6
            if [[ $ip =~ : ]]; then
                # IPv6
                ip rule add from all to $ip lookup vpn 2>/dev/null && echo "   ✅ IPv6: $ip" || echo "   ⚠️ IPv6 уже существует: $ip"
            else
                # IPv4
                ip rule add from all to $ip lookup vpn 2>/dev/null && echo "   ✅ IPv4: $ip" || echo "   ⚠️ IPv4 уже существует: $ip"
            fi
        fi
    done
fi

# Восстанавливаем таблицу vpn
echo ""
echo "🔄 Восстанавливаем таблицу vpn..."
ip route replace default dev $VPN_IFACE table vpn 2>/dev/null || true

# Очищаем кэш
ip route flush cache

echo ""
echo "✅ Настройка завершена!"
echo ""
echo "=== Проверка ==="

# Проверяем правила
echo "1. Правила для OpenRouter и OpenAI:"
ip rule show | grep -E "lookup vpn" | grep -E "104.18|2606:4700|api.openai" || echo "   ❌ Нет правил"

# Проверяем маршруты
echo ""
echo "2. Маршруты к OpenRouter:"
if [ -n "$OPENROUTER_IPS" ]; then
    echo "$OPENROUTER_IPS" | while read ip; do
        if [ -n "$ip" ]; then
            ROUTE=$(ip route get $ip 2>/dev/null)
            if echo "$ROUTE" | grep -q "table vpn"; then
                echo "   ✅ $ip → table vpn"
            elif echo "$ROUTE" | grep -q "dev tun"; then
                echo "   ✅ $ip → через VPN (tun)"
            else
                echo "   ❌ $ip → $(echo "$ROUTE" | head -1)"
            fi
        fi
    done
else
    echo "   ⚠️ Нет IP-адресов OpenRouter"
fi

echo ""
echo "3. Маршруты к OpenAI:"
if [ -n "$OPENAI_IPS" ]; then
    echo "$OPENAI_IPS" | while read ip; do
        if [ -n "$ip" ]; then
            ROUTE=$(ip route get $ip 2>/dev/null)
            if echo "$ROUTE" | grep -q "table vpn"; then
                echo "   ✅ $ip → table vpn"
            elif echo "$ROUTE" | grep -q "dev tun"; then
                echo "   ✅ $ip → через VPN (tun)"
            else
                echo "   ❌ $ip → $(echo "$ROUTE" | head -1)"
            fi
        fi
    done
else
    echo "   ⚠️ Нет IP-адресов OpenAI"
fi

# Проверяем таблицу vpn
echo ""
echo "4. Таблица vpn:"
ip route show table vpn 2>/dev/null | head -5 || echo "   ❌ Пустая"

# Тест доступности
echo ""
echo "=== Тест доступности ==="

# Тест OpenRouter
echo "Проверка OpenRouter:"
if curl -s --connect-timeout 5 https://openrouter.ai > /dev/null 2>&1; then
    echo "   ✅ OpenRouter доступен"
else
    echo "   ❌ OpenRouter недоступен"
fi

# Тест OpenAI
echo "Проверка OpenAI:"
if curl -s --connect-timeout 5 https://api.openai.com > /dev/null 2>&1; then
    echo "   ✅ OpenAI API доступен"
else
    echo "   ❌ OpenAI API недоступен"
fi

# Проверяем локальные сервисы
echo "Проверка локальных сервисов:"
if curl -s --connect-timeout 2 http://127.0.0.1 > /dev/null 2>&1 || curl -s --connect-timeout 2 http://localhost > /dev/null 2>&1; then
    echo "   ✅ Локальные сервисы доступны"
else
    echo "   ⚠️ Локальные сервисы проверьте отдельно"
fi

echo ""
echo "=== Рекомендации ==="
if ! curl -s --connect-timeout 5 https://openrouter.ai > /dev/null 2>&1; then
    echo "❌ OpenRouter недоступен"
    echo "Возможные причины:"
    echo "  1. VPN не подключен: adguardvpn-cli status"
    echo "  2. Неправильная локация VPN"
    echo "  3. Блокировка DNS"
    echo ""
    echo "Попробуйте:"
    echo "  1. adguardvpn-cli connect -l de"
    echo "  2. sudo ./agent_service/fix-vpn-routes.sh"
fi

if ! curl -s --connect-timeout 5 https://api.openai.com > /dev/null 2>&1; then
    echo ""
    echo "❌ OpenAI API недоступен"
    echo "Возможные причины:"
    echo "  1. VPN не подключен или неправильно настроен"
    echo "  2. Домен api.openai.com не добавлен в исключения VPN"
    echo "  3. Блокировка DNS"
    echo ""
    echo "Решение:"
    echo "  1. Добавить в исключения VPN: adguardvpn-cli site-exclusions add api.openai.com"
    echo "  2. Переподключить VPN: adguardvpn-cli connect -l de"
    echo "  3. Запустить исправление маршрутов: sudo ./agent_service/fix-vpn-routes.sh"
fi

echo ""
echo "=== Текущие правила маршрутизации ==="
ip rule show | grep -E "(880|vpn)" | head -10
