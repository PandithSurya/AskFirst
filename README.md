# AskFirst — AI Chat Application

ChatGPT-style app with multiple threads, persistent storage, universal memory, and multi-provider LLM support.

## Tech Stack
- **Backend**: FastAPI + SQLAlchemy + SQLite
- **Frontend**: Streamlit
- **Primary LLM**: Gemini 1.5 Flash
- **Fallback LLM**: Groq (LLaMA 3.1)

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# Edit .env and fill in GEMINI_API_KEY and GROQ_API_KEY

# 3. Start backend (terminal 1)
uvicorn main:app --reload

# 4. Start frontend (terminal 2)
streamlit run app.py
```

## Project Structure
```
AskFirst/
├── main.py           # FastAPI backend + all API endpoints
├── app.py            # Streamlit frontend
├── database.py       # SQLAlchemy models (Thread, Message, Memory)
├── llm_providers.py  # Provider abstraction (Gemini, Groq, Fallback)
├── memory_service.py # Universal memory injection + summarization
├── requirements.txt
└── .env.example
```

## API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/threads` | Create a new thread |
| GET | `/threads` | List all threads |
| GET | `/threads/{id}/messages` | Get messages in a thread |
| POST | `/chat` | Send message, get AI response |
| GET | `/memory` | View current memory summary |
| GET | `/health` | Health check |

## Adding New LLM Providers

To add Ollama, OpenAI, or OpenRouter, create a class in `llm_providers.py`:

```python
class OllamaProvider(LLMProvider):
    def generate_response(self, messages: list[dict]) -> str:
        import requests
        res = requests.post("http://localhost:11434/api/chat", json={
            "model": "llama3", "messages": messages, "stream": False
        })
        return res.json()["message"]["content"]
```

Then add it to `FallbackProvider.__init__` in the providers list.

## Universal Memory

The app maintains a single global memory summary across all threads. Every 5 user messages, the LLM re-reads all conversations and extracts key user facts (name, goals, preferences) into a bullet-point summary. This summary is injected into every system prompt, enabling cross-thread memory.
