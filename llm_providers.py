"""
LLM Provider abstraction layer.

To add a new provider (e.g. Ollama, OpenAI, OpenRouter):
1. Create a class that inherits from LLMProvider.
2. Implement generate_response(messages: list[dict]) -> str.
3. Add it to the fallback chain in get_llm_provider() or FallbackProvider.

Example for Ollama:
    class OllamaProvider(LLMProvider):
        def generate_response(self, messages):
            import requests
            res = requests.post("http://localhost:11434/api/chat", json={
                "model": "llama3", "messages": messages, "stream": False
            })
            return res.json()["message"]["content"]
"""
import os
from abc import ABC, abstractmethod
from dotenv import load_dotenv

load_dotenv()


class LLMProvider(ABC):
    @abstractmethod
    def generate_response(self, messages: list[dict]) -> str:
        pass


class GeminiProvider(LLMProvider):
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def generate_response(self, messages: list[dict]) -> str:
        # Convert OpenAI-style messages to Gemini format
        prompt_parts = []
        for m in messages:
            role = "User" if m["role"] == "user" else "Model"
            prompt_parts.append(f"{role}: {m['content']}")
        prompt = "\n".join(prompt_parts) + "\nModel:"
        response = self.model.generate_content(prompt)
        return response.text.strip()


class GroqProvider(LLMProvider):
    def __init__(self):
        from groq import Groq
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    def generate_response(self, messages: list[dict]) -> str:
        response = self.client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
        )
        return response.choices[0].message.content.strip()


class FallbackProvider(LLMProvider):
    """Tries providers in order, falls back on any exception."""

    def __init__(self):
        self._providers: list[LLMProvider] = []
        for cls in [GeminiProvider, GroqProvider]:
            try:
                self._providers.append(cls())
            except Exception:
                pass  # Skip provider if it can't be initialized

    def generate_response(self, messages: list[dict]) -> str:
        last_error = None
        for provider in self._providers:
            try:
                return provider.generate_response(messages)
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")


# Singleton instance used across the app
_provider_instance: FallbackProvider | None = None


def get_llm_provider() -> FallbackProvider:
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = FallbackProvider()
    return _provider_instance
