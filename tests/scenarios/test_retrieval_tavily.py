import pytest
import os
import json
import logging
from datetime import datetime
from graphs.retrieval import retrieval_graph
from state import RetrievalState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def save_test_log(scenario_name: str, state: dict):
    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(logs_dir, f"test_{scenario_name}_{timestamp}.json")
    
    serializable_state = {}
    for k, v in state.items():
        try:
            json.dumps(v)
            serializable_state[k] = v
        except:
            serializable_state[k] = str(v)

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(serializable_state, f, ensure_ascii=False, indent=2)
    logger.info(f"📝 Лог сохранен: {log_file}")

@pytest.mark.asyncio
async def test_retrieval_graph_tavily():
    """Сценарий: Только Tavily (Свежие новости/Интернет)."""
    scenario = "tavily_only"
    logger.info(f"🚀 Запуск сценария: {scenario}")
    
    initial_state = RetrievalState(
        question="Какие последние новости в области ИИ за последние 24 часа?",
        selected_sources=["web"], # Явно ограничиваем
        raw_results={},
        documents=[],
        prepared_material=""
    )
    
    final_state = await retrieval_graph.ainvoke(initial_state)
    save_test_log(scenario, final_state)
    
    assert "web" in final_state["selected_sources"]
    assert len(final_state["documents"]) > 0
    assert any(doc["type"] == "web" for doc in final_state["documents"])
    logger.info(f"✅ Tavily успешно отработал. Найдено документов: {len(final_state['documents'])}")