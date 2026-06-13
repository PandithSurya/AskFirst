"""
Streamlit frontend for AskFirst chat application.

Run with: streamlit run app.py
"""
import streamlit as st
import requests

API = "http://localhost:8000"

st.set_page_config(page_title="AskFirst", page_icon="💬", layout="wide")

# ── Helpers ───────────────────────────────────────────────────────────────────

def api_get(path: str):
    try:
        r = requests.get(f"{API}{path}", timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error(f"❌ Cannot connect to backend at: `{API}` — is it running?")
        st.stop()
    except requests.exceptions.Timeout:
        st.error(f"⏱ Backend timed out at: `{API}` — it may be waking up, try again in 30s")
        st.stop()
    except Exception as e:
        st.error(f"API error ({API}{path}): {e}")
        return None


def api_post(path: str, payload: dict):
    try:
        r = requests.post(f"{API}{path}", json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error(f"❌ Cannot connect to backend at: `{API}` — is it running?")
        st.stop()
    except requests.exceptions.Timeout:
        st.error(f"⏱ Backend timed out — it may be waking up, try again in 30s")
        st.stop()
    except Exception as e:
        st.error(f"API error ({API}{path}): {e}")
        return None


def api_delete(path: str):
    try:
        r = requests.delete(f"{API}{path}", timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Delete failed: {e}")
        return False


# ── Session State ─────────────────────────────────────────────────────────────

if "active_thread_id" not in st.session_state:
    st.session_state.active_thread_id = None
if "active_thread_title" not in st.session_state:
    st.session_state.active_thread_title = ""
if "confirm_delete" not in st.session_state:
    st.session_state.confirm_delete = None  # thread_id pending delete confirmation


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("💬 AskFirst")
    st.caption(f"Backend: `{API}`")
    st.divider()

    if st.button("➕ New Chat", use_container_width=True, type="primary"):
        result = api_post("/threads", {"title": "New Chat"})
        if result:
            st.session_state.active_thread_id = result["id"]
            st.session_state.active_thread_title = result["title"]
            st.session_state.confirm_delete = None
            st.rerun()

    st.markdown("**Threads**")
    threads = api_get("/threads") or []

    for thread in threads:
        label = thread["title"] if len(thread["title"]) <= 28 else thread["title"][:28] + "…"
        is_active = thread["id"] == st.session_state.active_thread_id
        col1, col2 = st.columns([5, 1])

        with col1:
            if st.button(
                f"{'▶ ' if is_active else ''}{label}",
                key=f"thread_{thread['id']}",
                use_container_width=True,
            ):
                st.session_state.active_thread_id = thread["id"]
                st.session_state.active_thread_title = thread["title"]
                st.session_state.confirm_delete = None
                st.rerun()

        with col2:
            if st.button("🗑", key=f"del_{thread['id']}", help="Delete thread"):
                st.session_state.confirm_delete = thread["id"]
                st.rerun()

        # Inline confirmation row
        if st.session_state.confirm_delete == thread["id"]:
            st.warning(f"Delete **{label}**?")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Yes", key=f"yes_{thread['id']}", type="primary", use_container_width=True):
                    if api_delete(f"/threads/{thread['id']}"):
                        if st.session_state.active_thread_id == thread["id"]:
                            st.session_state.active_thread_id = None
                            st.session_state.active_thread_title = ""
                        st.session_state.confirm_delete = None
                        st.rerun()
            with c2:
                if st.button("No", key=f"no_{thread['id']}", use_container_width=True):
                    st.session_state.confirm_delete = None
                    st.rerun()

    # Memory + DB verify panel
    st.divider()
    with st.expander("🧠 Memory Summary"):
        mem = api_get("/memory")
        if mem and mem.get("summary"):
            st.caption(mem["summary"])
        else:
            st.caption("No memory collected yet.")

    with st.expander("🔍 DB Verify"):
        if st.button("Run Check", use_container_width=True):
            info = api_get("/db/verify")
            if info:
                st.success(f"✅ DB is working")
                st.metric("Threads", info["threads"])
                st.metric("Total Messages", info["total_messages"])
                st.metric("User Messages", info["user_messages"])
                st.metric("Memory Summary Length", info["memory_summary_length"])
                if info["memory_preview"]:
                    st.caption("Memory preview:")
                    st.caption(info["memory_preview"])
                st.caption("Thread breakdown:")
                for t in info["all_threads"]:
                    st.caption(f"• [{t['id']}] {t['title']} — {t['message_count']} messages")


# ── Main Chat Area ────────────────────────────────────────────────────────────

if st.session_state.active_thread_id is None:
    st.markdown(
        """
        <div style='display:flex;flex-direction:column;align-items:center;justify-content:center;height:70vh;'>
            <h2>Welcome to AskFirst 👋</h2>
            <p style='color:gray;'>Select a thread or create a new chat to get started.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    thread_id = st.session_state.active_thread_id

    # Load messages
    messages = api_get(f"/threads/{thread_id}/messages") or []

    # Refresh thread title
    for t in (api_get("/threads") or []):
        if t["id"] == thread_id:
            st.session_state.active_thread_title = t["title"]
            break

    st.subheader(st.session_state.active_thread_title)
    st.divider()

    # Render message history
    chat_container = st.container()
    with chat_container:
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Input
    user_input = st.chat_input("Type your message…")

    if user_input:
        with chat_container:
            with st.chat_message("user"):
                st.markdown(user_input)

        with st.spinner("Thinking…"):
            result = api_post("/chat", {"thread_id": thread_id, "message": user_input})

        if result:
            with chat_container:
                with st.chat_message("assistant"):
                    st.markdown(result["assistant_message"]["content"])
            st.rerun()
