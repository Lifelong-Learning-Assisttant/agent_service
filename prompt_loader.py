"""
Модуль для загрузки промптов из текстовых файлов.
"""
import os
from typing import Optional


def load_prompt(prompt_name: str, **kwargs) -> str:
    """
    Загружает промпт из файла и подставляет переменные.
    
    Args:
        prompt_name: Имя файла промпта (без расширения)
        **kwargs: Переменные для подстановки в промпт
        
    Returns:
        Строка с промптом
        
    Raises:
        FileNotFoundError: Если файл промпта не найден
    """
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
    prompt_path = os.path.join(prompts_dir, f"{prompt_name}.txt")
    
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read().strip()
    
    # Подставляем переменные
    if kwargs:
        try:
            return prompt_template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing required variable: {e}")
    
    return prompt_template


def list_available_prompts() -> list[str]:
    """
    Возвращает список доступных промптов.
    
    Returns:
        Список имен файлов промптов (без расширения)
    """
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
    if not os.path.exists(prompts_dir):
        return []
    
    prompts = []
    for filename in os.listdir(prompts_dir):
        if filename.endswith(".txt"):
            prompts.append(filename[:-4])
    
    return sorted(prompts)