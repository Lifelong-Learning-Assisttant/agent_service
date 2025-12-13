from typing import Dict, Optional, TypedDict, Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage

from llm_service.llm_client import LLMClient
from settings import get_settings
from logger import get_logger
from langchain_tools import addition_service, make_tools


# ---------- Состояние графа ----------
class AgentState(TypedDict, total=False):
    """Общее состояние исполнения графа."""

    question: str
    route: Literal["direct", "tools"]
    answer: str
    meta: Dict[str, str]


# ---------- Агентная система ----------
class AgentSystem:
    """
    Агент на LangGraph с роутингом:
    - router → определяет маршрут 'direct' | 'tools'
    - answer_direct → отвечает напрямую через LLM
    - answer_with_tools → использует доступные инструменты для ответа
    """

    def __init__(self, provider: Optional[str] = None) -> None:
        """
        Args:
            provider: Провайдер LLM ('openai' | 'openrouter' | 'mistral').
                      Если None — берётся из настроек.
        """
        self.log = get_logger(__name__)
        cfg = get_settings()
        # Используем провайдер по умолчанию, если не указан
        prov = provider or cfg.default_provider
        self.client = LLMClient(provider=prov)
        self.cfg = cfg
        self.log.info("Инициализация агента: provider=%s", prov)

        # Инициализируем инструменты
        self.tools = make_tools()
        self.tool_names = [tool.name for tool in self.tools]
        self.log.info("Available tools: %s", self.tool_names)

        self.app = self._build_graph()

    # ---------- Узлы графа ----------
    def router(self, state: AgentState) -> AgentState:
        """
        Классифицирует запрос: direct | tools и возвращает обновлённый state.
        """
        import time

        q = (state.get("question") or "").strip()
        self.log.info("start:router | question_len=%d", len(q))
        t0 = time.perf_counter()

        # Сначала проверяем, нужно ли использовать инструменты
        if self._should_use_tools(q):
            route: Literal["direct", "tools"] = "tools"
            self.log.info("Router detected tool usage requirement")
        else:
            # Используем LLM для маршрутизации между direct
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
        self.log.info(
            "done:answer_direct | out_len=%d | %.1f ms", len(answer or ""), dt
        )
        return {**state, "answer": answer}

    def answer_with_tools(self, state: AgentState) -> AgentState:
        """
        Отвечает на вопрос, используя доступные инструменты.
        """
        import time
        import re

        q = (state.get("question") or "").strip()
        self.log.info("start:answer_with_tools | q_len=%d", len(q))
        t0 = time.perf_counter()

        # Проверяем, нужно ли использовать инструмент сложения
        if "addition_service" in q.lower() or "инструмент сложения" in q.lower():
            # Извлекаем числа из вопроса
            numbers = re.findall(r"\d+\.?\d*", q)
            if len(numbers) >= 2:
                try:
                    a = float(numbers[0])
                    b = float(numbers[1])

                    self.log.info(f"Using addition_service with a={a}, b={b}")
                    result = addition_service(a, b)

                    answer = (
                        f"Используя инструмент addition_service: {a} + {b} = {result}"
                    )
                    self.log.info(f"Tool result: {answer}")

                    dt = (time.perf_counter() - t0) * 1000
                    self.log.info(
                        "done:answer_with_tools | out_len=%d | %.1f ms",
                        len(answer or ""),
                        dt,
                    )
                    return {**state, "answer": answer}
                except Exception as e:
                    self.log.error(f"Tool execution failed: {e}")
                    answer = f"Ошибка при использовании инструмента: {str(e)}"

        # Проверяем, нужно ли использовать инструмент поиска RAG
        if "rag_search" in q.lower() or "поиск документов" in q.lower():
            try:
                from langchain_tools import rag_search
                
                self.log.info(f"Using rag_search tool for query: {q}")
                result = rag_search(q)
                
                answer = (
                    f"Результаты поиска через RAG:\n{result}"
                )
                self.log.info(f"RAG search result: {answer}")

                dt = (time.perf_counter() - t0) * 1000
                self.log.info(
                    "done:answer_with_tools | out_len=%d | %.1f ms",
                    len(answer or ""),
                    dt,
                )
                return {**state, "answer": answer}
            except Exception as e:
                self.log.error(f"RAG search tool execution failed: {e}")
                answer = f"Ошибка при поиске через RAG: {str(e)}"

        # Проверяем, нужно ли использовать инструмент генерации RAG
        if "rag_generate" in q.lower() or "сгенерировать ответ" in q.lower():
            try:
                from langchain_tools import rag_generate
                
                self.log.info(f"Using rag_generate tool for query: {q}")
                result = rag_generate(q)
                
                answer = (
                    f"Сгенерированный ответ через RAG:\n{result}"
                )
                self.log.info(f"RAG generate result: {answer}")

                dt = (time.perf_counter() - t0) * 1000
                self.log.info(
                    "done:answer_with_tools | out_len=%d | %.1f ms",
                    len(answer or ""),
                    dt,
                )
                return {**state, "answer": answer}
            except Exception as e:
                self.log.error(f"RAG generate tool execution failed: {e}")
                answer = f"Ошибка при генерации через RAG: {str(e)}"

        # Если инструмент не нужен, используем стандартный ответ
        answer = self.answer_direct(state).get("answer", "")
        return {**state, "answer": answer}

    # ---------- Ветвление ----------
    @staticmethod
    def _route_edge(state: AgentState) -> str:
        """Возвращает имя следующего узла по значению route."""
        route = state.get("route", "direct")
        return {
            "direct": "answer_direct",
            "tools": "answer_with_tools",
        }.get(route, "answer_direct")

    def _should_use_tools(self, question: str) -> bool:
        """Определяет, нужно ли использовать инструменты."""
        question_lower = question.lower()
        # Проверяем явное упоминание инструментов
        if any(
            tool in question_lower
            for tool in ["addition_service", "инструмент сложения", "rag_search", "поиск документов", "rag_generate", "сгенерировать ответ"]
        ):
            return True
        # Проверяем математические выражения
        if "+" in question and (
            "сколько" in question_lower or "посчитай" in question_lower
        ):
            return True
        return False

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
        builder.add_node("answer_with_tools", self.answer_with_tools)

        builder.add_edge(START, "router")
        builder.add_conditional_edges("router", self._route_edge)
        builder.add_edge("answer_direct", END)
        builder.add_edge("answer_with_tools", END)

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
