"""
Conversation memory management with persistence.
Stores chat history, user info, and provides context for LLM.
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Any
from collections import deque

from config import MAX_HISTORY_LENGTH, MAX_CONTEXT_MESSAGES, MEMORY_FILE_PATH, USE_REDIS, REDIS_HOST, REDIS_PORT

# Initialize redis client conditionally
redis_client = None
if USE_REDIS:
    try:
        # pyrefly: ignore [missing-import]
        import redis
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=0,
            decode_responses=True
        )
    except ImportError:
        print("Warning: redis package not installed, falling back to local file storage.")


class ConversationMemory:
    """
    Manages conversation history with persistence.
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
        
        # Trim if exceeds max history
        if len(self.messages) > MAX_HISTORY_LENGTH:
            self.messages = self.messages[-MAX_HISTORY_LENGTH:]
        
        # Auto-save after each message
        self._save_memory()
    
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
        self._save_memory()
    
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
        self._save_memory()
    
    def clear(self) -> None:
        """Clear conversation history but keep user info."""
        self.messages = []
        self._save_memory()
    
    def reset_all(self) -> None:
        """Reset everything including user info."""
        self.messages = []
        self.user_info = {
            "name": None,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        }
        self.crisis_flags = []
        self.stats.clear()
        self.stats.update({
            "total_messages": 0,
            "crisis_count": 0,
            "crisis_escalations": 0,
            "off_topic_redirects": 0,
            "offensive_content_blocks": 0,
            "languages_detected": [],
            "name_learned": False
        })
        self._save_memory()
    
    def __len__(self) -> int:
        """Return number of messages."""
        return len(self.messages)
    
    def _get_memory_path(self) -> str:
        """Get the memory file path for this session."""
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(MEMORY_FILE_PATH) or ".", exist_ok=True)
        return f"{MEMORY_FILE_PATH}.{self.session_id}.json"
    
    def _save_memory(self) -> None:
        """Save memory to Redis or fallback local file."""
        try:
            data = {
                "session_id": self.session_id,
                "messages": self.messages,
                "user_info": self.user_info,
                "crisis_flags": self.crisis_flags,
                "stats": self.stats,
                "last_saved": datetime.now().isoformat()
            }
            if USE_REDIS and redis_client:
                # Save key with 24 hours expiry (86400 seconds)
                redis_client.setex(
                    f"mindspace:session:{self.session_id}",
                    24 * 3600,
                    json.dumps(data, ensure_ascii=False)
                )
            else:
                with open(self._get_memory_path(), 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving memory: {e}")
    
    def _load_memory(self) -> None:
        """Load memory from Redis or fallback local file."""
        try:
            loaded_data = None
            if USE_REDIS and redis_client:
                data_str = redis_client.get(f"mindspace:session:{self.session_id}")
                if data_str:
                    loaded_data = json.loads(data_str)
            else:
                path = self._get_memory_path()
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        loaded_data = json.load(f)
            
            if loaded_data:
                self.messages = loaded_data.get("messages", [])
                self.user_info = loaded_data.get("user_info", self.user_info)
                self.crisis_flags = loaded_data.get("crisis_flags", [])
                loaded_stats = loaded_data.get("stats", {})
                for k, v in loaded_stats.items():
                    self.stats[k] = v
        except Exception as e:
            print(f"Error loading memory: {e}")
    
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
        
    # Delete from Redis if enabled
    if USE_REDIS and redis_client:
        try:
            redis_client.delete(f"mindspace:session:{session_id}")
        except Exception as e:
            print(f"Error deleting memory from Redis: {e}")
            
    # Also delete the file
    try:
        path = f"{MEMORY_FILE_PATH}.{session_id}.json"
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Error deleting memory file: {e}")