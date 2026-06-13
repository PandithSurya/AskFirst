"""
Universal Memory Service.

Maintains a single summary of facts learned across ALL threads.
Before each response, memory is injected into the system prompt.
Memory is updated after EVERY user message (not just every 5th).
When no summary exists yet, raw cross-thread messages are injected directly.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from database import Memory, Message


SUMMARY_PROMPT_TEMPLATE = """You are a memory summarizer. Extract key facts about the user (name, preferences, goals, background) from the conversations below. Return ONLY a concise bullet-point list. No filler.

Previous Summary:
{previous_summary}

All Conversations:
{messages}

Updated Summary (bullet points only):"""


def get_memory_summary(db: Session) -> str:
    memory = db.query(Memory).first()
    return memory.summary if memory else ""


def get_cross_thread_context(db: Session, current_thread_id: int) -> str:
    """Return raw messages from OTHER threads to use when summary is not yet built."""
    messages = (
        db.query(Message)
        .filter(Message.thread_id != current_thread_id, Message.role == "user")
        .order_by(Message.timestamp.asc())
        .limit(50)
        .all()
    )
    if not messages:
        return ""
    return "\n".join(f"- {m.content}" for m in messages)


def build_system_prompt(
    memory_summary: str,
    thread_history: list[dict],
    user_message: str,
    cross_thread_context: str = "",
) -> str:
    if memory_summary:
        memory_section = memory_summary
    elif cross_thread_context:
        memory_section = f"[Raw context from other conversations]:\n{cross_thread_context}"
    else:
        memory_section = "No prior context available."

    history_text = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}" for m in thread_history
    )
    return f"""You are a helpful AI assistant with persistent memory across conversations.
Always use the memory/context below to answer questions about the user.

Known User Memory:
{memory_section}

Current Conversation:
{history_text}

Current User Message:
{user_message}"""


def update_memory_summary(db: Session, llm_provider, reset: bool = False) -> None:
    """Regenerate the global memory summary from all messages across all threads.
    Pass reset=True to rebuild from scratch, ignoring the previous summary.
    """
    all_messages = (
        db.query(Message)
        .order_by(Message.timestamp.asc())
        .limit(200)
        .all()
    )
    # If no messages remain after a delete, wipe the summary entirely
    if not all_messages:
        memory = db.query(Memory).first()
        if memory:
            memory.summary = ""
            memory.updated_at = datetime.utcnow()
            db.commit()
        return

    previous_summary = "" if reset else get_memory_summary(db)
    messages_text = "\n".join(
        f"{m.role.capitalize()}: {m.content}" for m in all_messages
    )
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        previous_summary=previous_summary,
        messages=messages_text,
    )
    try:
        new_summary = llm_provider.generate_response([
            {"role": "user", "content": prompt}
        ])
        memory = db.query(Memory).first()
        if memory:
            memory.summary = new_summary
            memory.updated_at = datetime.utcnow()
        else:
            db.add(Memory(summary=new_summary))
        db.commit()
    except Exception:
        pass  # Non-critical: keep old summary on failure
