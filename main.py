"""
FastAPI backend for AskFirst chat application.

Run with: uvicorn main:app --reload
"""
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Thread, Message, Memory, get_db, init_db
from llm_providers import get_llm_provider
from memory_service import (
    get_memory_summary,
    get_cross_thread_context,
    build_system_prompt,
    update_memory_summary,
)

app = FastAPI(title="AskFirst Chat API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ── Schemas ──────────────────────────────────────────────────────────────────

class ThreadCreate(BaseModel):
    title: str = "New Chat"


class ThreadOut(BaseModel):
    id: int
    title: str
    created_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    thread_id: int
    role: str
    content: str
    timestamp: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    thread_id: int
    message: str


class ChatResponse(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/threads", response_model=ThreadOut, status_code=201)
def create_thread(payload: ThreadCreate, db: Session = Depends(get_db)):
    thread = Thread(title=payload.title)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@app.get("/threads", response_model=list[ThreadOut])
def list_threads(db: Session = Depends(get_db)):
    return db.query(Thread).order_by(Thread.created_at.desc()).all()


@app.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
def get_messages(thread_id: int, db: Session = Depends(get_db)):
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return (
        db.query(Message)
        .filter(Message.thread_id == thread_id)
        .order_by(Message.timestamp.asc())
        .all()
    )


@app.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: int, db: Session = Depends(get_db)):
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    db.delete(thread)  # cascade will delete messages too
    db.commit()
    # Rebuild memory from scratch so deleted thread's info is fully forgotten
    llm = get_llm_provider()
    update_memory_summary(db, llm, reset=True)


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    thread = db.query(Thread).filter(Thread.id == payload.thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Auto-title thread from first user message
    if thread.title == "New Chat":
        thread.title = payload.message[:60]
        db.commit()

    # Persist user message
    user_msg = Message(
        thread_id=payload.thread_id,
        role="user",
        content=payload.message.strip(),
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Build conversation history for this thread (exclude the message just added)
    history = (
        db.query(Message)
        .filter(Message.thread_id == payload.thread_id)
        .order_by(Message.timestamp.asc())
        .all()
    )
    thread_history = [{"role": m.role, "content": m.content} for m in history[:-1]]

    # Use summarized memory if available, otherwise inject raw cross-thread user messages
    memory_summary = get_memory_summary(db)
    cross_thread = "" if memory_summary else get_cross_thread_context(db, payload.thread_id)
    system_prompt = build_system_prompt(memory_summary, thread_history, payload.message, cross_thread)

    # Generate response
    llm = get_llm_provider()
    try:
        ai_text = llm.generate_response([{"role": "user", "content": system_prompt}])
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Persist assistant message
    assistant_msg = Message(
        thread_id=payload.thread_id,
        role="assistant",
        content=ai_text,
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    # Always refresh memory summary after every message
    update_memory_summary(db, llm)

    return ChatResponse(user_message=user_msg, assistant_message=assistant_msg)


@app.get("/memory")
def get_memory(db: Session = Depends(get_db)):
    return {"summary": get_memory_summary(db)}


@app.get("/db/verify")
def verify_db(db: Session = Depends(get_db)):
    """Diagnostic endpoint to verify DB is working and show row counts."""
    threads = db.query(Thread).count()
    messages = db.query(Message).count()
    user_messages = db.query(Message).filter(Message.role == "user").count()
    memory = db.query(Memory).first()
    summary = memory.summary if memory else ""
    return {
        "status": "ok",
        "threads": threads,
        "total_messages": messages,
        "user_messages": user_messages,
        "memory_summary_length": len(summary),
        "memory_preview": summary[:300] + ("..." if len(summary) > 300 else ""),
        "all_threads": [
            {"id": t.id, "title": t.title, "message_count": len(t.messages)}
            for t in db.query(Thread).all()
        ],
    }


@app.get("/")
def root():
    return {"status": "ok", "app": "AskFirst API"}


@app.get("/health")
def health():
    return {"status": "ok"}
