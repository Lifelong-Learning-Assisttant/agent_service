"""
Инструменты для работы с алгоритмическими задачами.
"""
import os
import json
import aiofiles
from langchain.tools import tool

@tool
async def get_algo_problem_info(problem_id: str) -> str:
    """Возвращает информацию о задаче."""
    base_path = f"../data/algo_problems/{problem_id}"
    try:
        info = {"problem_id": problem_id}
        for filename, key in [("task.md", "task_description"), ("interviewer_note.md", "interviewer_notes")]:
            path = os.path.join(os.path.dirname(__file__), "..", base_path, filename)
            if os.path.exists(path):
                async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
                    info[key] = await f.read()
        return json.dumps(info, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

@tool
async def get_algo_solution(problem_id: str) -> str:
    """Возвращает эталонное решение."""
    path = os.path.join(os.path.dirname(__file__), "..", f"../data/algo_problems/{problem_id}/hidden_solution.py")
    try:
        if os.path.exists(path):
            async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
                return json.dumps({"solution": await f.read()}, ensure_ascii=False)
        return json.dumps({"error": "Solution not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})