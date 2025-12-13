#!/usr/bin/env python3
"""
FastAPI приложение для агента.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from agent_system import AgentSystem

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
        answer = agent.run(request.question, request.session_id)
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
        # Здесь можно добавить логику для завершения сессии, если это необходимо
        return {"status": "success", "message": "Session ended", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Запуск приложения
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8250)
