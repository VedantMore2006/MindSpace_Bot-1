"""
Conversation memory management with SQLite persistence.
Stores chat history, user info, and provides context for LLM.
"""

import json
from datetime import datetime
from typing import List, Dict, Optional, Any

from config import MAX_HISTORY_LENGTH, MAX_CONTEXT_MESSAGES
from db import Session, ChatSession, Message


class ConversationMemory:
    """
    Manages conversation history with SQLite persistence.
    Stores messages, user info, and provides context for LLM.
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: List[Dict[str, Any]] = []
        self.user_info: Dict[str, Any] = {
            "name": None,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        }
        self.crisis_flags: List[Dict] = []
        self.stats: Dict[str, Any] = {
            "total_messages": 0,
            "crisis_count": 0,
            "crisis_escalations": 0,
            "off_topic_redirects": 0,
            "offensive_content_blocks": 0,
            "languages_detected": [],
            "name_learned": False
        }
        self._load_memory()
    
    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        self.messages.append(message)
        self.stats["total_messages"] += 1
        self.user_info["last_seen"] = datetime.now().isoformat()
        
        # Trim local messages list if it exceeds max history
        if len(self.messages) > MAX_HISTORY_LENGTH:
            self.messages = self.messages[-MAX_HISTORY_LENGTH:]
        
        # Save to SQLite database
        self._save_message_to_db(role, content)
    
    def get_context_for_llm(self, max_messages: int = MAX_CONTEXT_MESSAGES) -> str:
        """
        Get formatted conversation context for LLM.
        Returns a string with recent conversation history.
        """
        if not self.messages:
            return "No previous conversation."
        
        # Get recent messages
        recent = self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        
        # Format for LLM
        context_lines = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else "Assistant"
            context_lines.append(f"{role}: {msg['content']}")
        
        context = "\n".join(context_lines)
        
        # Add user info if available
        if self.user_info["name"]:
            context = f"User's name is {self.user_info['name']}.\n{context}"
        
        return context
    
    def get_recent_messages(self, count: int = 5) -> List[Dict]:
        """Get recent messages."""
        return self.messages[-count:] if self.messages else []
    
    def get_user_name(self) -> Optional[str]:
        """Get user's name if known."""
        return self.user_info.get("name")
    
    def set_user_name(self, name: str) -> None:
        """Store user's name."""
        self.user_info["name"] = name
        self._save_session_metadata()
    
    def get_user_info(self) -> Dict:
        """Get user information."""
        return self.user_info.copy()
    
    def add_crisis_flag(self, message: str, severity: str = "HIGH") -> None:
        """Record a crisis detection."""
        self.crisis_flags.append({
            "message": message,
            "severity": severity,
            "timestamp": datetime.now().isoformat()
        })
        self.stats["crisis_count"] += 1
        self._save_session_metadata()
    
    def clear(self) -> None:
        """Clear conversation history but keep user info."""
        self.messages = []
        with Session() as db_session:
            db_session.query(Message).filter_by(session_id=self.session_id).delete()
            db_session.commit()
    
    def reset_all(self) -> None:
        """Reset everything including user info."""
        self.messages = []
        self.user_info = {
            "name": None,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        }
        self.crisis_flags = []
        self.stats = {
            "total_messages": 0,
            "crisis_count": 0,
            "crisis_escalations": 0,
            "off_topic_redirects": 0,
            "offensive_content_blocks": 0,
            "languages_detected": [],
            "name_learned": False
        }
        with Session() as db_session:
            db_session.query(Message).filter_by(session_id=self.session_id).delete()
            db_sess = db_session.query(ChatSession).filter_by(session_id=self.session_id).first()
            if db_sess:
                db_sess.user_name = None
                db_sess.user_id = None
                db_sess.last_seen = datetime.now()
                db_sess.stats_json = json.dumps({
                    "stats": self.stats,
                    "crisis_flags": self.crisis_flags
                })
            db_session.commit()
    
    def __len__(self) -> int:
        """Return number of messages."""
        return len(self.messages)
    
    def _save_message_to_db(self, role: str, content: str) -> None:
        """Save a message directly to SQLite."""
        try:
            with Session() as db_session:
                # Insert the message
                db_msg = Message(
                    session_id=self.session_id,
                    role=role,
                    content=content,
                    timestamp=datetime.now()
                )
                db_session.add(db_msg)
                
                # Update the session stats and last_seen
                db_sess = db_session.query(ChatSession).filter_by(session_id=self.session_id).first()
                if db_sess:
                    db_sess.last_seen = datetime.now()
                    db_sess.user_name = self.user_info.get("name")
                    db_sess.stats_json = json.dumps({
                        "stats": self.stats,
                        "crisis_flags": self.crisis_flags
                    })
                db_session.commit()
        except Exception as e:
            print(f"Error saving message to database: {e}")
            
    def _save_memory(self) -> None:
        """Compatibility wrapper for saving session metadata."""
        self._save_session_metadata()

    def _save_session_metadata(self) -> None:
        """Save session metadata (user info, stats) to SQLite."""
        try:
            with Session() as db_session:
                db_sess = db_session.query(ChatSession).filter_by(session_id=self.session_id).first()
                if db_sess:
                    db_sess.last_seen = datetime.now()
                    db_sess.user_name = self.user_info.get("name")
                    db_sess.stats_json = json.dumps({
                        "stats": self.stats,
                        "crisis_flags": self.crisis_flags
                    })
                db_session.commit()
        except Exception as e:
            print(f"Error saving session metadata to database: {e}")
    
    def _load_memory(self) -> None:
        """Load memory and messages from SQLite."""
        try:
            with Session() as db_session:
                db_sess = db_session.query(ChatSession).filter_by(session_id=self.session_id).first()
                
                if not db_sess:
                    # Create new session entry
                    db_sess = ChatSession(
                        session_id=self.session_id,
                        user_id=None,
                        user_name=None,
                        created_at=datetime.now(),
                        last_seen=datetime.now(),
                        stats_json=json.dumps({
                            "stats": self.stats,
                            "crisis_flags": self.crisis_flags
                        })
                    )
                    db_session.add(db_sess)
                    db_session.commit()
                else:
                    self.user_info = {
                        "name": db_sess.user_name,
                        "first_seen": db_sess.created_at.isoformat() if db_sess.created_at else datetime.now().isoformat(),
                        "last_seen": db_sess.last_seen.isoformat() if db_sess.last_seen else datetime.now().isoformat()
                    }
                    if db_sess.stats_json:
                        try:
                            stats_data = json.loads(db_sess.stats_json)
                            self.stats = stats_data.get("stats", self.stats)
                            self.crisis_flags = stats_data.get("crisis_flags", [])
                        except Exception:
                            pass
                
                # Fetch history messages
                db_messages = db_session.query(Message).filter_by(session_id=self.session_id).order_by(Message.id.asc()).all()
                self.messages = []
                for msg in db_messages:
                    self.messages.append({
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now().isoformat()
                    })
        except Exception as e:
            print(f"Error loading memory from database: {e}")
    
    def get_stats(self) -> Dict:
        """Get memory statistics."""
        return {
            "total_messages": self.stats.get("total_messages", 0),
            "crisis_count": self.stats.get("crisis_count", 0),
            "history_length": len(self.messages),
            "user_name": self.get_user_name(),
            "first_seen": self.user_info.get("first_seen"),
            "last_seen": self.user_info.get("last_seen")
        }


# Session factory
_memory_store: Dict[str, ConversationMemory] = {}


def get_memory(session_id: Optional[str] = None) -> ConversationMemory:
    """
    Get or create a ConversationMemory instance for a session.
    """
    if not session_id:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    if session_id not in _memory_store:
        _memory_store[session_id] = ConversationMemory(session_id)
    
    return _memory_store[session_id]


def clear_memory(session_id: str) -> None:
    """Clear memory for a specific session."""
    if session_id in _memory_store:
        _memory_store[session_id].clear()


def delete_memory(session_id: str) -> None:
    """Delete memory for a specific session."""
    if session_id in _memory_store:
        _memory_store[session_id].reset_all()
        del _memory_store[session_id]
        
    # Delete from SQLite
    try:
        with Session() as db_session:
            db_session.query(Message).filter_by(session_id=session_id).delete()
            db_session.query(ChatSession).filter_by(session_id=session_id).delete()
            db_session.commit()
    except Exception as e:
        print(f"Error deleting memory from SQLite: {e}")