#!/usr/bin/env python3
"""
FastAPI приложение для агента.
"""

import argparse
import json
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncio
import uuid
from datetime import datetime, timezone

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

# Хранилище WebSocket соединений по session_id
ws_connections: Dict[str, List[WebSocket]] = {}

# Модель для запроса
class AgentRequest(BaseModel):
    question: str
    session_id: Optional[str] = "default"

# Модель для ответа
class AgentResponse(BaseModel):
    answer: str
    session_id: str
    status: str

# Модель для прогресс-события
class ProgressEvent(BaseModel):
    event_id: str
    session_id: str
    step: str
    tool: Optional[str] = None
    message: str
    level: str
    ts: str
    meta: Optional[Dict[str, Any]] = None

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

# Эндпоинт для получения истории сообщений
@app.get("/api/messages")
async def get_messages(session_id: str = "default"):
    """
    Возвращает историю сообщений для сессии.
    """
    try:
        session = agent.get_session(session_id)
        if not session:
            return {"messages": [], "session_id": session_id}
        
        # Возвращаем историю в формате (author, text)
        messages = []
        for event in session.last_events:
            if event["step"] == "final_answer":
                messages.append(("Agent", event["meta"].get("final_answer", "")))
            elif event["step"] == "start_run":
                messages.append(("User", event["meta"].get("question", "")))
            elif event["level"] == "info":
                messages.append(("System", event["message"]))
        
        return {"messages": messages, "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Эндпоинт для получения прогресс-событий (polling)
@app.get("/api/agent/progress")
async def get_progress(session_id: str = "default"):
    """
    Возвращает последние прогресс-события для сессии.
    """
    try:
        session = agent.get_session(session_id)
        if not session:
            return {"events": [], "session_id": session_id}
        
        return {"events": list(session.last_events), "session_id": session_id}
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

# WebSocket endpoint для подписки на события
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket для получения real-time событий прогресса.
    """
    await websocket.accept()
    session_id = None
    
    try:
        # Ожидаем сообщение подписки
        data = await websocket.receive_json()
        if data.get("cmd") == "subscribe":
            session_id = data.get("session_id")
            if not session_id:
                await websocket.send_json({"type": "error", "message": "session_id required"})
                await websocket.close()
                return
            
            # Добавляем соединение в хранилище
            if session_id not in ws_connections:
                ws_connections[session_id] = []
            ws_connections[session_id].append(websocket)
            
            # Подтверждаем подписку
            await websocket.send_json({
                "type": "subscribed",
                "session_id": session_id,
                "message": f"Subscribed to session {session_id}"
            })
            
            # Ждем отключения
            while True:
                try:
                    data = await websocket.receive_json()
                    # Обработка входящих сообщений (например, unsubscribe)
                    if data.get("cmd") == "unsubscribe":
                        break
                except WebSocketDisconnect:
                    break
                except Exception:
                    # Игнорируем ошибки парсинга
                    pass
    except Exception as e:
        pass
    finally:
        # Удаляем соединение при отключении
        if session_id and session_id in ws_connections:
            if websocket in ws_connections[session_id]:
                ws_connections[session_id].remove(websocket)
            if not ws_connections[session_id]:
                del ws_connections[session_id]

# Эндпоинт для получения прогресс-событий от агента (вызывается из AgentSession.notify_ui)
@app.post("/api/agent/progress")
async def receive_progress(event: ProgressEvent):
    """
    Получает прогресс-событие от агента и рассылает подписчикам.
    """
    try:
        # Преобразуем в формат для WebSocket
        ws_message = {
            "type": "progress",
            "step": event.step,
            "details": event.message,
            "session_id": event.session_id,
            "tool": event.tool,
            "level": event.level,
            "meta": event.meta
        }
        
        # Отправляем всем подписчикам этой сессии
        if event.session_id in ws_connections:
            disconnected = []
            for ws in ws_connections[event.session_id]:
                try:
                    await ws.send_json(ws_message)
                except Exception:
                    disconnected.append(ws)
            
            # Удаляем отключенных
            for ws in disconnected:
                if ws in ws_connections[event.session_id]:
                    ws_connections[event.session_id].remove(ws)
        
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Эндпоинт для проверки состояния агента
@app.get("/api/agent/status")
async def get_agent_status():
    """
    Возвращает статус агента.
    """
    return {"status": "ready"}

# Запуск приложения
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
