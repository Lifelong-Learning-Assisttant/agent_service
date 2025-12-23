from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field
import json
import os

ProviderName = Literal["openai", "openrouter", "mistral"]


def load_app_settings():
    """Загружает настройки из app_settings.json или из переменной окружения APP_SETTINGS_PATH."""
    # Проверяем переменную окружения для кастомного пути
    custom_path = os.getenv("APP_SETTINGS_PATH")
    if custom_path:
        app_settings_path = custom_path
    else:
        app_settings_path = os.path.join(os.path.dirname(__file__), "app_settings.json")
    
    if os.path.exists(app_settings_path):
        with open(app_settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


class LLMSettings(BaseSettings):
    """
    Глобальные настройки клиента LLM/Embeddings.
    - Загружает значения из переменных окружения с префиксом LLM_ и из .env.
    - Отсутствие переменных окружения НЕ приводит к ошибкам — используются дефолты.
    """
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Общие ----
    default_provider: ProviderName = Field(default="openai")

    # ---- Логирование (одна переменная на функциональность) ----
    log_level: str = Field(default="INFO")

    # ---- OpenAI ----
    openai_chat_model: str = Field(default="gpt-4o-mini")
    openai_emb_model: str = Field(default="text-embedding-3-small")
    openai_api_key: SecretStr | None = Field(default=None)

    # ---- OpenRouter ----
    openrouter_chat_model: str = Field(default="openrouter/auto")
    openrouter_emb_model: str = Field(default="text-embedding-3-small")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    openrouter_api_key: SecretStr | None = Field(default=None)

    # Таймауты и ретраи
    request_timeout_s: float = 60.0
    connect_timeout_s: float = 10.0
    max_retries: int = 5
    retry_base_s: float = 1.0
    retry_max_s: float = 20.0
    retry_jitter_s: float = 0.5

    # ---- External MCPs & App-level settings ----
    # (URLs можно задавать через переменные окружения CONTEXT7_URL, TAVILY_URL, ADDITION_SERVICE_URL, RAG_SERVICE_URL, TEST_GENERATOR_SERVICE_URL)
    context7_url: str | None = Field(default=None)
    tavily_url: str | None = Field(default=None)
    addition_service_url: str | None = Field(default=None)
    rag_service_url: str | None = Field(default=None)
    test_generator_service_url: str | None = Field(default=None)
    context7_api_key: SecretStr | None = Field(default=None)
    http_timeout_s: float = Field(default=60.0)

    # Батч для эмбеддингов
    emb_batch_size: int = Field(default=64)

    # ---- Mistral ----
    mistral_chat_model: str = Field(default="mistral-large-latest")
    mistral_emb_model: str = Field(default="mistral-embed")
    mistral_api_key: SecretStr | None = Field(default=None)
    
    # ---- Системный промпт ----
    system_prompt: str = Field(default="")

    def __init__(self, **kwargs):
        """Инициализирует настройки, загружая значения из app_settings.json."""
        super().__init__(**kwargs)
        
        app_settings = load_app_settings()
        
        # Применяем настройки из app_settings.json после инициализации
        # Это гарантирует, что настройки из app_settings.json перепишут дефолтные значения
        for key, value in app_settings.items():
            if hasattr(self, key):
                current_value = getattr(self, key)
                field_info = self.__class__.model_fields.get(key)
                if field_info and current_value == field_info.default:
                    setattr(self, key, value)
        
        # Загружаем системный промпт из файла, если он не был переопределён
        if not self.system_prompt:
            system_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
            if os.path.exists(system_prompt_path):
                with open(system_prompt_path, "r", encoding="utf-8") as f:
                    self.system_prompt = f.read().strip()


def get_settings() -> LLMSettings:
    """
    Возвращает НОВЫЙ экземпляр настроек.
    (Без синглтона: каждый вызов создаёт объект заново.)
    """
    return LLMSettings()


if __name__ == "__main__":

    import os

    print("=== LLMSettings mini-test ===")
    s = get_settings()
    
    # Выводим информацию только о тех провайдерах, для которых есть API ключ
    providers_with_keys = []
    if s.openai_api_key and s.openai_api_key.get_secret_value():
        providers_with_keys.append("openai")
        print("OpenAI provider:")
        print("  - chat_model:", s.openai_chat_model)
        print("  - base_url:", s.openai_base_url)
    
    if s.openrouter_api_key and s.openrouter_api_key.get_secret_value():
        providers_with_keys.append("openrouter")
        print("OpenRouter provider:")
        print("  - chat_model:", s.openrouter_chat_model)
        print("  - base_url:", s.openrouter_base_url)
    
    if s.mistral_api_key and s.mistral_api_key.get_secret_value():
        providers_with_keys.append("mistral")
        print("Mistral provider:")
        print("  - chat_model:", s.mistral_chat_model)
        print("  - base_url:", s.mistral_base_url)
    
    print("\nDefault provider:", s.default_provider)
    print("Available providers with API keys:", providers_with_keys)
