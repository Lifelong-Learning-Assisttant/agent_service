#!/usr/bin/env python3
"""
FastAPI приложение для агента.
"""

import argparse
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from agent_system import AgentSystem
from settings import get_settings

# Парсинг аргументов командной строки
parser = argparse.ArgumentParser(description='Agent Service')
parser.add_argument('--settings', default='app_settings.json', help='Path to settings file')
args, unknown = parser.parse_known_args()

# Устанавливаем переменную окружения для пути к конфигу
import os
os.environ["APP_SETTINGS_PATH"] = os.path.abspath(args.settings)

# Загрузка настроек через settings
cfg = get_settings()
AGENT_PORT = cfg.agent_port if hasattr(cfg, 'agent_port') else 8250

# Создание приложения FastAPI
app = FastAPI()

# Инициализация агента
agent = AgentSystem()

# Модель для запроса
class AgentRequest(BaseModel):
    question: str
    session_id: Optional[str] = "default"

# Модель для ответа
class AgentResponse(BaseModel):
    answer: str
    session_id: str
    status: str

# Эндпоинт для запуска агента
@app.post("/api/agent/run")
async def run_agent(request: AgentRequest):
    """
    Запускает агента для обработки вопроса.
    """
    try:
        answer = await agent.run(request.question, request.session_id)
        return AgentResponse(
            answer=answer,
            session_id=request.session_id,
            status="success"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Эндпоинт для проверки состояния агента
@app.get("/api/agent/status")
async def get_agent_status():
    """
    Возвращает статус агента.
    """
    return {"status": "ready"}

# Эндпоинт для завершения сессии
@app.post("/api/agent/end_session")
async def end_session(session_id: Optional[str] = "default"):
    """
    Завершает сессию агента.
    """
    try:
        session = agent.get_session(session_id)
        if session:
            await session.cancel()
            agent.remove_session(session_id)
        return {"status": "success", "message": "Session ended", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Эндпоинт для получения списка активных сессий
@app.get("/api/agent/sessions")
async def get_sessions():
    """
    Возвращает список активных сессий.
    """
    sessions_info = []
    for session_id, session in agent.sessions.items():
        sessions_info.append({
            "session_id": session_id,
            "is_running": session.is_running(),
            "created_at": session.created_at.isoformat(),
            "last_active_at": session.last_active_at.isoformat(),
            "age_seconds": session.get_age_seconds()
        })
    return {"sessions": sessions_info}

# Запуск приложения
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
