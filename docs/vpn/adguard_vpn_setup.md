# AdGuard VPN CLI: Настройка и использование

## Установка

### 1. Установка AdGuard VPN CLI

```bash
# Установка релизной версии
curl -fsSL https://raw.githubusercontent.com/AdguardTeam/AdGuardVPNCLI/master/scripts/release/install.sh | sh -s -- -v

# Согласитесь на создание symlink в /usr/local/bin (нажмите Y)
```

### 2. Вход в аккаунт

```bash
# Войдите или создайте аккаунт
adguardvpn-cli login
```

[Зарегистрируйтесь на сайте](https://auth.adguardaccount.com/login.html?_plc=en) если у вас еще нет аккаунта.

## Базовая настройка

### 3. Установка режима selective (рекомендуется)

Режим **selective** означает, что VPN будет использоваться ТОЛЬКО для доменов из списка исключений. Все остальные сайты и сервисы работают без VPN.

```bash
# Установить режим selective
adguardvpn-cli site-exclusions mode selective
```

### 2. Добавление доменов в список исключений

```bash
# Добавить домены для доступа через VPN
adguardvpn-cli site-exclusions add openrouter.ai
adguardvpn-cli site-exclusions add api.openrouter.ai
adguardvpn-cli site-exclusions add api.openai.com
```

### 3. Проверка настроек

```bash
# Показать текущий режим
adguardvpn-cli site-exclusions mode

# Показать список исключений
adguardvpn-cli site-exclusions show
```

Пример вывода:
```
Current exclusion mode is SELECTIVE
Exclusions for SELECTIVE mode:
openrouter.ai
api.openrouter.ai
api.openai.com
```

### 4. Важное примечание про OpenAI API

**OpenAI API требует VPN для доступа из России**. Если вы получаете ошибку:
```
Error code: 403 - {'error': {'code': 'unsupported_country_region_territory', 'message': 'Country, region, or territory not supported'}}
```

Это означает, что OpenAI блокирует доступ из российских IP-адресов.

**Решение**:
1. Убедитесь, что `api.openai.com` добавлен в исключения VPN
2. Подключите VPN к локации, где доступен OpenAI (например, Германия)
3. Запустите скрипт исправления маршрутов: `sudo ./agent_service/fix-vpn-routes.sh`
4. Проверьте доступность: `curl -I https://api.openai.com`

**Альтернативный подход**: Если VPN не помогает, можно использовать:
- OpenRouter (уже настроен) как прокси к OpenAI моделям
- Другие провайдеры API, доступные в вашем регионе

## Подключение к VPN

### 1. Список доступных локаций

```bash
adguardvpn-cli list-locations
```

Вывод:
```
ISO   COUNTRY              CITY                           PING ESTIMATE
DE    Germany              Frankfurt                      69        
NL    Netherlands          Amsterdam                      50        
GB    United Kingdom       London                         53        
...
```

### 2. Подключение

```bash
# Подключиться к Германии (Франкфурт)
adguardvpn-cli connect -l de

# Или по названию города
adguardvpn-cli connect -l Frankfurt

# Или по стране
adguardvpn-cli connect -l Germany

# Быстрое подключение (выберет лучшую локацию)
adguardvpn-cli connect
```

### 3. Проверка статуса

```bash
adguardvpn-cli status
```

Пример вывода:
```
Connected to FRANKFURT in TUN mode, running on tun0
SELECTIVE exclusion mode is used. The tunnel is only active for 2 exclusions
```

## Отключение от VPN

```bash
adguardvpn-cli disconnect
```

## Полный цикл настройки (рекомендуемый)

```bash
# 1. Установить режим selective
adguardvpn-cli site-exclusions mode selective

# 2. Добавить домены (OpenRouter + OpenAI)
adguardvpn-cli site-exclusions add openrouter.ai
adguardvpn-cli site-exclusions add api.openrouter.ai
adguardvpn-cli site-exclusions add api.openai.com

# 3. Проверить настройки
adguardvpn-cli site-exclusions show
adguardvpn-cli site-exclusions mode

# 4. Подключиться к VPN
adguardvpn-cli connect -l de

# 5. Проверить статус
adguardvpn-cli status

# 6. Исправить маршруты (ВАЖНО!)
sudo ./agent_service/fix-vpn-routes.sh

# 7. Проверить доступность
curl -I https://openrouter.ai
curl -I https://api.openai.com
```

## Дополнительные команды

### Удалить домен из списка исключений
```bash
adguardvpn-cli site-exclusions remove openrouter.ai
```

### Очистить все исключения
```bash
adguardvpn-cli site-exclusions clear
```

### Переключить режим на ALL (весь трафик через VPN)
```bash
adguardvpn-cli site-exclusions mode all
```

### Проверить обновления
```bash
adguardvpn-cli check-update
adguardvpn-cli update
```

### Войти в другой аккаунт
```bash
adguardvpn-cli login
```

### Выйти из аккаунта
```bash
adguardvpn-cli logout
```

### Показать версию
```bash
adguardvpn-cli --version
```

### Показать все команды
```bash
adguardvpn-cli --help-all
```

## Важные замечания

### Бесплатная версия
- Доступно ограниченное количество локаций (см. `list-locations`)
- Более низкая скорость по сравнению с платной версией
- Для получения большего количества локаций и более высокой скорости нужен апгрейд

### Режимы работы
- **SELECTIVE** - VPN только для указанных доменов (рекомендуется)
- **ALL** - весь трафик идет через VPN

### После переподключения VPN
После каждого переподключения VPN **обязательно** запускайте скрипт исправления маршрутов:
```bash
sudo ./agent_service/fix-vpn-routes.sh
```

**Важно**: Без запуска скрипта OpenRouter может стать недоступен из-за неправильных правил маршрутизации.

Смотрите подробности в [open_router_vpn.md](./open_router_vpn.md)

## Диагностика проблем

### Проверить маршруты
```bash
ip route show
ip route show table vpn
```

### Проверить правила маршрутизации
```bash
ip rule list
```

### Проверить, через какой интерфейс идет трафик
```bash
# Проверить трафик к openrouter
ip route get 104.18.2.115

# Проверить трафик к локальным сервисам
ip route get 127.0.0.1
```

### Проверить DNS
```bash
nslookup openrouter.ai
nslookup google.com
```

## См. также
- [Инструкция по настройке маршрутов](./open_router_vpn.md)
- [Скрипт исправления маршрутов](../fix-vpn-routes.sh)
