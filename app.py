# agent_service/app.py  -- обновлённый кусок
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from agent_service.langchain_agent import LangchainAgentService
from agent_service.config import get_settings

log = logging.getLogger("agent_service")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="LLM Agent with LangChain AgentExecutor")
settings = get_settings()

# создаём агент один раз при старте
AGENT_SERVICE = LangchainAgentService(provider=None, temperature=0.2, verbose=False)


class MessageIn(BaseModel):
    message: str
    provider: Optional[str] = None


class MessageOut(BaseModel):
    answer: str


@app.post("/v1/message", response_model=MessageOut)
def handle_message(payload: MessageIn):
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    # Если пользователь указал provider — можно создать отдельный агент на лету.
    if payload.provider and payload.provider != settings.default_provider:
        local_agent = LangchainAgentService(provider=payload.provider, temperature=0.2, verbose=False)
        answer = local_agent.run(payload.message)
    else:
        answer = AGENT_SERVICE.run(payload.message)

    return MessageOut(answer=answer)
