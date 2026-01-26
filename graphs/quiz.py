import logging
import os
import json
import re
from typing import Dict, List, Any, Optional, Literal

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from state import AgentState
from graphs.retrieval import retrieval_graph
from llm_service.llm_client import LLMClient
from settings import get_settings
from langchain_tools import grade_exam_async

log = logging.getLogger(__name__)

# --- Helper to load prompts ---

def load_prompt(filename: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

# --- Models for Structured Output ---

class QuizRouterOutput(BaseModel):
    """Output of the internal quiz router."""
    action: Literal["answer", "skip", "help", "stop", "search"] = Field(
        description="The action to take: 'answer' (user provides an answer), 'skip' (user wants to skip), 'help' (user asks for a hint), 'stop' (user wants to end the quiz), 'search' (user asks a technical question requiring RAG)"
    )
    reasoning: str = Field(description="Brief explanation of the action choice")

class OpenJudgeOutput(BaseModel):
    """Output of the open-ended question judge."""
    is_correct: bool
    score: float
    reasoning: str
    explanation: str

# --- Nodes ---

async def quiz_router_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Determines the next action within the quiz subgraph using deterministic rules and LLM fallback.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(
            step="quiz_router",
            message="Анализ действия в квизе...",
            tool="quiz_router"
        )

    question = (state.get("question") or "").strip()
    interaction_mode = state.get("interaction_mode", "AI_SYNC")
    
    # 1. Слэш-команды (высший приоритет)
    if question == "/skip_question":
        return {"intent": "skip_question", "final_answer": None}
    if question == "/finish_quizz":
        return {"intent": "evaluate_quiz", "final_answer": None}

    # 2. Детерминированный MCQ ответ
    if question.startswith("/answer"):
        return {"intent": "quiz_answering", "final_answer": None}

    # 3. Детерминированный открытый ответ (режим ANSWER_QUIZ)
    # Если пользователь пишет текст в режиме ответа, это принудительно ответ.
    if interaction_mode == "ANSWER_QUIZ":
        return {"intent": "quiz_answering", "final_answer": None}

    # 4. Вопрос "по вопросу" (режим AI_SYNC + знак вопроса)
    if interaction_mode == "AI_SYNC" and "?" in question:
        return {"intent": "rag_answer", "final_answer": None}

    # 5. Если интент уже установлен (например, в Supervisor), доверяем ему
    if state.get("intent") in ["skip_question", "evaluate_quiz", "rag_answer"]:
        return {"intent": state.get("intent"), "final_answer": None}

    # 6. Fallback: LLM Router (для неоднозначных случаев)
    template = load_prompt("quiz_router.txt")
    if not template:
        log.error("quiz_router.txt prompt not found")
        return {"intent": "quiz_answering", "final_answer": None}

    prompt = template.format(question=question)
    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    parser = JsonOutputParser(pydantic_object=QuizRouterOutput)
    
    chat = client.create_chat(temperature=0)
    res = chat.invoke([
        HumanMessage(content=prompt + "\n\n" + parser.get_format_instructions())
    ])
    
    try:
        output = parser.parse(res.content)
        action = output.get("action", "answer")
    except Exception as e:
        log.error(f"Failed to parse quiz router output: {e}")
        action = "answer"

    intent_map = {
        "answer": "quiz_answering",
        "skip": "skip_question",
        "help": "quiz_answering", 
        "stop": "evaluate_quiz",
        "search": "rag_answer"
    }

    if session:
        await session.notify_ui(
            step="quiz_router_done",
            message=f"Действие: {action}",
            tool="quiz_router",
            meta={"action": action}
        )

    return {"intent": intent_map.get(action, "quiz_answering"), "final_answer": None}

async def mcq_judge_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Validates MCQ answers (Single/Multiple Choice) algorithmically.
    """
    idx = state.get("current_quiz_index", 0)
    questions = state.get("quiz_questions", [])
    user_msg = (state.get("question") or "").strip()
    
    if idx >= len(questions):
        return {"intent": "evaluate_quiz"}

    current_q = questions[idx]
    # Ожидаем формат: /answer [0, 2]
    match = re.search(r"\[(.*?)\]", user_msg)
    if not match:
        # Если формат неверный, пробуем считать это текстовым ответом (fallback)
        return await open_judge_node(state, config)

    try:
        selected_indices = [int(i.strip()) for i in match.group(1).split(",") if i.strip()]
    except:
        return await open_judge_node(state, config)

    # В объекте вопроса от test_generator правильные индексы лежат в 'correct'
    # Но в нашем _parse_quiz_result мы их теряли. Нужно будет обновить парсер.
    # Пока предполагаем, что они есть в объекте.
    correct_indices = current_q.get("correct_indices", [])
    
    is_correct = set(selected_indices) == set(correct_indices)
    score = 1.0 if is_correct else 0.0
    
    # Сохраняем результат в историю
    history_item = {
        "index": idx,
        "question": current_q["q"],
        "user_input": user_msg,
        "is_correct": is_correct,
        "score": score,
        "type": "mcq"
    }
    
    quiz_history = list(state.get("quiz_history", []))
    quiz_history.append(history_item)
    
    # Переходим к объяснению (Explanation)
    return {
        "quiz_history": quiz_history,
        "last_evaluation": history_item,
        "intent": "explain" # Новый внутренний интент
    }

async def open_judge_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Validates open-ended answers using LLM-as-a-Judge.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(step="open_judge", message="Оценка вашего ответа...", tool="interviewer")

    idx = state.get("current_quiz_index", 0)
    questions = state.get("quiz_questions", [])
    user_msg = state.get("question", "")
    
    if idx >= len(questions):
        return {"intent": "evaluate_quiz"}

    current_q = questions[idx]
    
    template = load_prompt("quiz_interviewer_judge.txt")
    prompt = template.format(
        question=current_q["q"],
        reference_answer=current_q.get("a", "N/A"),
        user_answer=user_msg
    )

    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    parser = JsonOutputParser(pydantic_object=OpenJudgeOutput)
    
    chat = client.create_chat(temperature=0)
    res = chat.invoke([HumanMessage(content=prompt + "\n\n" + parser.get_format_instructions())])
    
    try:
        eval_data = parser.parse(res.content)
    except:
        eval_data = {
            "is_correct": False,
            "score": 0.0,
            "reasoning": "Ошибка парсинга оценки.",
            "explanation": "Не удалось оценить ответ."
        }

    history_item = {
        "index": idx,
        "question": current_q["q"],
        "user_input": user_msg,
        **eval_data,
        "type": "open"
    }
    
    quiz_history = list(state.get("quiz_history", []))
    quiz_history.append(history_item)
    
    return {
        "quiz_history": quiz_history,
        "last_evaluation": history_item,
        "intent": "explain"
    }

async def explainer_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Generates a brief explanation for the current question based on evaluation.
    """
    eval_data = state.get("last_evaluation", {})
    idx = state.get("current_quiz_index", 0)
    questions = state.get("quiz_questions", [])
    
    current_q = questions[idx]
    
    # Если у нас уже есть explanation от судьи (в открытых вопросах), используем его.
    # Если нет (в MCQ), генерируем.
    explanation = eval_data.get("explanation")
    
    if not explanation:
        template = load_prompt("quiz_interviewer_explain.txt")
        prompt = template.format(
            question=current_q["q"],
            correct_answer=current_q.get("a", "N/A"),
            is_correct="Верно" if eval_data.get("is_correct") else "Неверно",
            reasoning=eval_data.get("reasoning", "")
        )
        
        settings = get_settings()
        client = LLMClient(provider=settings.default_provider)
        chat = client.create_chat(temperature=0.3)
        res = chat.invoke([HumanMessage(content=prompt)])
        explanation = res.content

    prefix = "✅ **Верно!**" if eval_data.get("is_correct") else "❌ **Не совсем.**"
    
    return {"final_answer": f"{prefix}\n\n{explanation}"}

async def interviewer_hint_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Provides a hint using RAG context.
    """
    session = config.get("configurable", {}).get("session") if config else None
    if session:
        await session.notify_ui(step="interviewer_hint", message="Подготовка подсказки...", tool="interviewer")
    
    idx = state.get("current_quiz_index", 0)
    questions = state.get("quiz_questions", [])
    user_msg = state.get("question", "")
    material = state.get("prepared_material", "")
    
    current_q = questions[idx]["q"] if idx < len(questions) else "N/A"
    
    template = load_prompt("quiz_interviewer_hint.txt")
    prompt = template.format(
        current_question=current_q,
        material=material,
        user_msg=user_msg
    )
    
    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    chat = client.create_chat(temperature=0.7)
    res = chat.invoke([HumanMessage(content=prompt)])
    
    return {"final_answer": res.content}

async def skip_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Marks the current question as skipped.
    """
    idx = state.get("current_quiz_index", 0)
    questions = state.get("quiz_questions", [])
    
    history_item = {
        "index": idx,
        "question": questions[idx]["q"] if idx < len(questions) else "N/A",
        "user_input": "[SYSTEM: SKIPPED]",
        "is_correct": False,
        "score": 0.0,
        "reasoning": "Вопрос пропущен пользователем.",
        "type": "skip"
    }
    
    quiz_history = list(state.get("quiz_history", []))
    quiz_history.append(history_item)
    
    return {"quiz_history": quiz_history, "final_answer": None}

async def check_progress_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Checks if there are more questions and returns the next one.
    """
    idx = state.get("current_quiz_index", 0)
    questions = state.get("quiz_questions", [])
    
    next_idx = idx + 1
    finished = next_idx >= len(questions)
    
    if finished:
        return {"intent": "evaluate_quiz"}
    
    next_q = questions[next_idx]["q"]
    session = config.get("configurable", {}).get("session") if config else None
    
    response_msg = f"Принято. Вопрос №{next_idx + 1}:\n{next_q}"
    
    # Если мы пришли сюда после объяснения, добавляем его к ответу
    prev_answer = state.get("final_answer", "")
    if prev_answer:
        response_msg = f"{prev_answer}\n\n---\n\n**Вопрос №{next_idx + 1}:**\n{next_q}"

    if session:
        await session.notify_ui(
            step="quizz_question",
            message=response_msg,
            tool="interviewer",
            meta={"current_quiz_index": next_idx, "total_questions": len(questions)}
        )
        
    return {
        "current_quiz_index": next_idx,
        "final_answer": f"[SYSTEM: NEXT_QUESTION] {response_msg}"
    }

async def mentor_node(state: AgentState, config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Mentor role: provides final feedback using quiz_history.
    """
    session = config.get("configurable", {}).get("session") if config else None
    
    history = state.get("quiz_history", [])
    
    if history and not state.get("quiz_questions") == []: # Ещё не очищено
        if session:
            await session.notify_ui(step="mentor_eval", message="Подведение итогов...", tool="mentor")
            
        detailed_report = []
        total_score = 0.0
        for item in history:
            total_score += item.get("score", 0.0)
            detailed_report.append(
                f"**Вопрос {item['index']+1}:** {item['question']}\n"
                f"**Ответ:** {item['user_input']}\n"
                f"**Оценка:** {'✅' if item['is_correct'] else '❌'} ({item.get('reasoning', '')})\n"
            )

        template = load_prompt("quiz_mentor_feedback.txt")
        prompt = template.format(
            total_questions=len(history),
            evaluation_result=f"Средний балл: {total_score / len(history):.2f}",
            detailed_report="\n".join(detailed_report)
        )
        
        settings = get_settings()
        client = LLMClient(provider=settings.default_provider)
        chat = client.create_chat(temperature=0.3)
        res = chat.invoke([HumanMessage(content=prompt)])
        
        final_answer = (
            f"📊 **Результаты квиза**\n"
            f"Всего вопросов: {len(history)}\n"
            f"Верных ответов: {sum(1 for x in history if x['is_correct'])}\n\n"
            f"{res.content}"
        )
        
        return {
            "final_answer": final_answer,
            "quiz_questions": [], 
            "current_quiz_index": 0,
            "user_answers": [],
            "quiz_history": [] # Clear after mentor
        }
    
    # Follow-up chat
    template = load_prompt("quiz_mentor_discussion.txt")
    prompt = template.format(question=state.get('question'))
    settings = get_settings()
    client = LLMClient(provider=settings.default_provider)
    chat = client.create_chat(temperature=0.7)
    res = chat.invoke([HumanMessage(content=prompt)])
    
    return {"final_answer": res.content}

# --- Router Logic ---

def route_quiz(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "skip_question":
        return "skip"
    if intent == "evaluate_quiz":
        return "mentor"
    if intent == "rag_answer":
        return "search"
    
    # Для quiz_answering выбираем тип судьи
    question = (state.get("question") or "").strip()
    if question.startswith("/answer"):
        return "mcq_judge"
    return "open_judge"

# --- Graph Assembly ---

def build_quiz_graph():
    builder = StateGraph(AgentState)
    
    builder.add_node("quiz_router", quiz_router_node)
    builder.add_node("mcq_judge", mcq_judge_node)
    builder.add_node("open_judge", open_judge_node)
    builder.add_node("explainer", explainer_node)
    builder.add_node("interviewer_hint", interviewer_hint_node)
    builder.add_node("skip", skip_node)
    builder.add_node("check_progress", check_progress_node)
    builder.add_node("mentor", mentor_node)
    builder.add_node("retrieval", retrieval_graph)
    
    builder.add_edge(START, "quiz_router")
    
    builder.add_conditional_edges(
        "quiz_router",
        route_quiz,
        {
            "mcq_judge": "mcq_judge",
            "open_judge": "open_judge",
            "skip": "skip",
            "mentor": "mentor",
            "search": "retrieval"
        }
    )
    
    builder.add_edge("mcq_judge", "explainer")
    builder.add_edge("open_judge", "explainer")
    builder.add_edge("explainer", "check_progress")
    
    builder.add_edge("retrieval", "interviewer_hint")
    builder.add_edge("interviewer_hint", END)
    
    builder.add_edge("skip", "check_progress")
    
    builder.add_conditional_edges(
        "check_progress",
        lambda s: "mentor" if s.get("intent") == "evaluate_quiz" else END,
        {
            "mentor": "mentor",
            END: END
        }
    )
    
    builder.add_edge("mentor", END)
    
    return builder.compile()

quiz_graph = build_quiz_graph()