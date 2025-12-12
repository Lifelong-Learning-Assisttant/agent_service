from typing import Dict, Optional, TypedDict, Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage 

from llm_service.llm_client import LLMClient
from settings import get_settings
from logger import get_logger


# ---------- Моки инструментов (tools) ----------
def rag_fetch_mock(question: str) -> str:
    """
    Мок RAG-поиска: возвращает фиктивный контекст.
    Args:
        question: Вопрос пользователя.
    Returns:
        Строка с псевдо-контекстом.
    """
    return (
        "Контекст (мок): это фиктивные выдержки из базы знаний. "
        f"Ключевые слова: {question[:80]}..."
    )


def quiz_make_mock(topic: str) -> str:
    """
    Мок конструктора квизов: возвращает 3 простых вопроса по теме.
    Args:
        topic: Тема квиза.
    Returns:
        Строка с чек-листом вопросов.
    """
    return (
        f"Квиз по теме «{topic}» (мок):\n"
        "1) Дайте краткое определение темы.\n"
        "2) Перечислите 3 ключевые особенности.\n"
        "3) Приведите практический пример применения."
    )


# ---------- Состояние графа ----------
class AgentState(TypedDict, total=False):
    """Общее состояние исполнения графа."""
    question: str
    route: Literal["direct", "rag", "quiz"]
    answer: str
    meta: Dict[str, str]


# ---------- Агентная система ----------
class RoutingAgentSystem:
    """
    Простой агент на LangGraph с роутингом:
    - router → определяет маршрут 'direct' | 'rag' | 'quiz'
    - answer_direct → отвечает напрямую через LLM
    - answer_rag → использует мок RAG + LLM
    - answer_quiz → генерирует квиз (мок) + LLM оформление
    """

    def __init__(self, provider: Optional[str] = None) -> None:
        """
        Args:
            provider: Провайдер LLM ('openai' | 'openrouter' | 'mistral').
                      Если None — берётся из настроек.
        """
        self.log = get_logger(__name__)
        cfg = get_settings()
        self.client = LLMClient(provider=provider or cfg.default_provider)
        self.cfg = cfg
        self.log.info("Инициализация агента: provider=%s", provider or cfg.default_provider)
        self.app = self._build_graph()

    # ---------- Узлы графа ----------
    def router(self, state: AgentState) -> AgentState:
        """
        Классифицирует запрос: direct | rag | quiz и возвращает обновлённый state.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:router | question_len=%d", len(q))
        t0 = time.perf_counter()

        system = (
            "Ты — маршрутизатор запросов. Верни ОДНО слово: "
            "'direct' если на вопрос можно ответить напрямую; "
            "'rag' если потребуется внешний контекст; "
            "'quiz' если пользователь просит тест/викторину/вопросы."
        )
        prompt = f"{system}\n\nВопрос: {q}\nОтвет:"
        route_raw = (self.client.generate([prompt], temperature=0.0)[0] or "").strip().lower()

        if any(w in route_raw for w in ("quiz", "виктор", "тест")):
            route: Literal["direct", "rag", "quiz"] = "quiz"
        elif any(w in route_raw for w in ("rag", "контекст", "поиск")):
            route = "rag"
        else:
            route = "direct"

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:router | route=%s | %.1f ms", route, dt)
        return {**state, "route": route}

    def answer_direct(self, state: AgentState) -> AgentState:
        """
        Прямой ответ через LLM без инструментов.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:answer_direct | q_len=%d", len(q))
        t0 = time.perf_counter()

        prompt = (
            "Ответь кратко и по делу, оформи в 1–2 абзаца; при необходимости добавь список.\n\n"
            f"Вопрос: {q}"
        )
        answer = self.client.generate([prompt], temperature=0.2)[0]

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:answer_direct | out_len=%d | %.1f ms", len(answer or ""), dt)
        return {**state, "answer": answer}

    def answer_rag(self, state: AgentState) -> AgentState:
        """
        Мок RAG: подмешиваем фиктивный контекст и просим LLM ответить с учётом контекста.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:answer_rag | q_len=%d", len(q))
        t0 = time.perf_counter()

        context = rag_fetch_mock(q)
        prompt = (
            "Ответь, используя предоставленный контекст. Если в контексте нет ответа — скажи об этом явно.\n\n"
            f"[КОНТЕКСТ]\n{context}\n\n"
            f"[ВОПРОС]\n{q}\n\n"
            "Ответ:"
        )
        answer = self.client.generate([prompt], temperature=0.2)[0]

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:answer_rag | out_len=%d | %.1f ms", len(answer or ""), dt)
        return {**state, "answer": answer}

    def answer_quiz(self, state: AgentState) -> AgentState:
        """
        Мок квиза: генерим каркас вопросов и просим LLM оформить.
        """
        import time

        topic = (state.get("question") or "").strip()
        self.log.info("start:answer_quiz | topic_len=%d", len(topic))
        t0 = time.perf_counter()

        base_quiz = quiz_make_mock(topic)
        prompt = (
            "Оформи квиз аккуратно: к каждому вопросу добавь краткую подсказку и критерий оценки.\n\n"
            f"{base_quiz}\n\n"
            "Формат: список вопросов → ниже к каждому одна подсказка и критерий."
        )
        answer = self.client.generate([prompt], temperature=0.3)[0]

        dt = (time.perf_counter() - t0) * 1000
        self.log.info("done:answer_quiz | out_len=%d | %.1f ms", len(answer or ""), dt)
        return {**state, "answer": answer}

    # ---------- Ветвление ----------
    @staticmethod
    def _route_edge(state: AgentState) -> str:
        """Возвращает имя следующего узла по значению route."""
        route = state.get("route", "direct")
        return {
            "direct": "answer_direct",
            "rag": "answer_rag",
            "quiz": "answer_quiz",
        }.get(route, "answer_direct")

    # ---------- Сборка графа ----------
    def _build_graph(self):
        """
        Собирает и компилирует граф.
        Returns:
            Скомпилированный граф (Runnable).
        """
        self.log.debug("build_graph: begin")
        builder = StateGraph(AgentState)
        builder.add_node("router", self.router)
        builder.add_node("answer_direct", self.answer_direct)
        builder.add_node("answer_rag", self.answer_rag)
        builder.add_node("answer_quiz", self.answer_quiz)

        builder.add_edge(START, "router")
        builder.add_conditional_edges("router", self._route_edge)
        builder.add_edge("answer_direct", END)
        builder.add_edge("answer_rag", END)
        builder.add_edge("answer_quiz", END)

        app = builder.compile()
        self.log.debug("build_graph: done")
        return app

    # ---------- Публичный вызов ----------
    def run(self, question: str) -> str:
        """
        Запускает граф на один вопрос.
        Args:
            question: Вопрос пользователя.
        Returns:
            Финальный ответ строкой.
        """
        import time

        self.log.info("run: start | q_len=%d", len(question or ""))
        t0 = time.perf_counter()
        final_state: AgentState = self.app.invoke({"question": question})
        answer = final_state.get("answer", "")
        dt = (time.perf_counter() - t0) * 1000
        self.log.info("run: done  | out_len=%d | %.1f ms", len(answer or ""), dt)

        # опционально – совместимость с UI, где ожидают AIMessage
        _ = AIMessage(content=answer)
        return answer


if __name__ == "__main__":
    agent = RoutingAgentSystem()  # провайдер берётся из settings.default_provider
    print(agent.run("Сделай мини-викторину по Python list comprehension."))
    print("---")
    print(agent.run("Что такое LangGraph и когда его применять?"))
    print("---")
    print(agent.run("Сумма преимуществ использования RAG в HR-ассистенте?"))
