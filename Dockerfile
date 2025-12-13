# Dockerfile для agent_service
FROM python:3.13-slim

# Устанавливаем gcc, g++ и uv
RUN apt-get update && apt-get install -y gcc g++
RUN pip install uv

# Копируем файлы проекта
WORKDIR /app
COPY pyproject.toml .

# Устанавливаем зависимости
RUN uv sync

# Запускаем sh, чтобы контейнер не умер
CMD ["sh"]