# agent_service/app.py  -- обновлённый кусок
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from llm_service.llm_client import LLMClient
from settings import get_settings

log = logging.getLogger("agent_service")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="LLM Agent with LangChain AgentExecutor")
settings = get_settings()

# создаём LLM-клиент один раз при старте
LLM_CLIENT = LLMClient(provider=settings.default_provider)


class MessageIn(BaseModel):
    message: str
    provider: Optional[str] = None


class MessageOut(BaseModel):
    answer: str


@app.post("/v1/message", response_model=MessageOut)
def handle_message(payload: MessageIn):
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    # Если пользователь указал provider — можно создать отдельный LLM-клиент на лету.
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
