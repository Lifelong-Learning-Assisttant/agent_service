from typing import Dict, List, Any, Optional, Literal, TypedDict, Annotated
import operator
from langchain_core.messages import BaseMessage

class AgentState(TypedDict, total=False):
    """Общее состояние исполнения графа."""
    messages: List[BaseMessage]
    question: str
    intent: Literal["general", "rag_answer", "generate_quiz", "evaluate_quiz", "quiz_answering", "skip_question", "algo_help"]
    problem_id: str                 # ID текущей задачи (например, valid_parentheses)
    user_code: str                  # Текущий код пользователя
    documents: List[Dict[str, Any]] # Список унифицированных документов {content, source, score}
    prepared_material: str          # Синтезированный "Golden Source" в Markdown
    is_relevant: bool               # Флаг достаточности информации
    
    # Поля для интерактивного квиза
    quiz_questions: List[Dict[str, str]]  # Список {"question": "...", "answer": "..."}
    current_quiz_index: int               # Индекс текущего вопроса
    user_answers: List[str]               # Ответы пользователя
    
    final_answer: str
    thought: str                          # Рассуждения модели (reasoning)
    
    # Режимы и настройки
    interaction_mode: str                 # AI_SYNC | ANSWER_QUIZ | ALGOS
    mode: str                             # qa | quiz | algos
    app_settings: Any

class RetrievalState(AgentState):
    """Специфичное состояние для подграфа поиска."""
    selected_sources: List[str]           # rag, web, docs
    library_id: Optional[str]             # Разрешенный ID библиотеки для Context7
    # Используем reducer для объединения результатов из параллельных веток
    raw_results: Annotated[Dict[str, Any], operator.ior]