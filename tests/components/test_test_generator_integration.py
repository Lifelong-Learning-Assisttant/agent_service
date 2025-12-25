# agent_service/test_test_generator_integration.py
"""
Скрипт для тестирования асинхронной интеграции с сервисом test_generator.
"""
import sys
import json
import asyncio
sys.path.append('/app')
from langchain_tools import generate_exam_async, grade_exam_async


async def test_generate_exam_async():
    """Тест асинхронной генерации экзамена."""
    markdown_content = """# Test Section 1

This is the first section of the test content.

## Subsection 1.1

This is a subsection with more details.

# Test Section 2

This is the second section of the test content.

## Subsection 2.1

This is another subsection with additional details.
"""
    config = {
        "total_questions": 5,
        "single_choice_count": 3,
        "multiple_choice_count": 1,
        "open_ended_count": 1,
        "provider": "local"
    }
    
    print("Testing generate_exam_async...")
    result = await generate_exam_async(markdown_content, config)
    result_dict = json.loads(result)
    
    if "error" in result_dict:
        print(f"Error: {result_dict['error']}")
        return False
    
    print(f"Generated exam: {result_dict}")
    return True


async def test_grade_exam_async():
    """Тест асинхронной оценки экзамена."""
    # Сначала сгенерируем экзамен
    markdown_content = """# Test Section 1

This is the first section of the test content.

## Subsection 1.1

This is a subsection with more details.

# Test Section 2

This is the second section of the test content.

## Subsection 2.1

This is another subsection with additional details.
"""
    config = {
        "total_questions": 5,
        "single_choice_count": 3,
        "multiple_choice_count": 1,
        "open_ended_count": 1,
        "provider": "local"
    }
    
    # Генерируем экзамен
    generate_result = await generate_exam_async(markdown_content, config)
    generate_result_dict = json.loads(generate_result)
    
    if "error" in generate_result_dict:
        print(f"Error generating exam: {generate_result_dict['error']}")
        return False
    
    exam_id = generate_result_dict["exam_id"]
    
    # Формируем ответы
    answers = []
    for question in generate_result_dict["questions"]:
        if question["type"] == "open_ended":
            answers.append({
                "question_id": question["id"],
                "text_answer": "This is a test answer."
            })
        else:
            answers.append({
                "question_id": question["id"],
                "choice": question["correct"]
            })
    
    print("Testing grade_exam_async...")
    result = await grade_exam_async(exam_id, answers)
    result_dict = json.loads(result)
    
    if "error" in result_dict:
        print(f"Error: {result_dict['error']}")
        return False
    
    print(f"Graded exam: {result_dict}")
    return True


async def main():
    """Основная функция тестирования."""
    print("Starting async test_generator integration tests...")
    
    success = True
    success &= await test_generate_exam_async()
    success &= await test_grade_exam_async()
    
    if success:
        print("All async tests passed!")
    else:
        print("Some async tests failed!")


if __name__ == "__main__":
    asyncio.run(main())