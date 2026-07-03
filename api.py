"""
FastAPI application for MindSpace Chatbot.
Provides REST API endpoints for chatbot integration.
"""

from fastapi import FastAPI, HTTPException, Depends, status, Request
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import uuid
import logging
import os
import time
from collections import defaultdict

from main import MindSpaceChatbot
from conversation_memory import get_memory, clear_memory
from language_support import detect_language

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Rate Limiting
# ============================================================================
class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests: Dict[str, List[float]] = defaultdict(list)
    
    def check(self, client_id: str) -> bool:
        """Check if request is allowed."""
        now = time.time()
        # Clean old requests
        self.requests[client_id] = [t for t in self.requests[client_id] if now - t < 60]
        
        if len(self.requests[client_id]) >= self.requests_per_minute:
            return False
        
        self.requests[client_id].append(now)
        return True

rate_limiter = RateLimiter(requests_per_minute=60)

# API Key Verification
security = HTTPBearer()
API_KEY = os.getenv("CONVERSATIONAL_BOT_API_KEY")

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if API_KEY and credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key."
        )
    return credentials.credentials

# ============================================================================
# Pydantic Models for API
# ============================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., description="User's message to the chatbot", min_length=1, max_length=5000)
    session_id: Optional[str] = Field(None, description="Unique session identifier")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    user_name: Optional[str] = Field(None, description="Optional user name")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Hello, I'm feeling very stressed today",
                "session_id": "session_20260623_114702",
                "user_id": "user_12345"
            }
        }


class ChatResponse(BaseModel):
    response: str = Field(..., description="Chatbot's response message")
    session_id: str = Field(..., description="Current session identifier")
    message_id: str = Field(..., description="Unique message identifier")
    timestamp: str = Field(..., description="Response timestamp")
    is_crisis: bool = Field(False, description="Whether this was a crisis response")
    is_offensive: bool = Field(False, description="Whether offensive content was blocked")
    language: str = Field("en", description="Detected language of the conversation")
    user_name: Optional[str] = Field(None, description="User's name if known")

    class Config:
        json_schema_extra = {
            "example": {
                "response": "I hear you. Stress can feel really heavy. Can you tell me what's been causing it lately?",
                "session_id": "session_20260623_114702",
                "message_id": "msg_20260623_114702_001",
                "timestamp": "2026-06-23T11:47:17.166510",
                "is_crisis": False,
                "is_offensive": False,
                "language": "en",
                "user_name": "Alex"
            }
        }


class SessionStats(BaseModel):
    session_id: str
    total_messages: int
    history_length: int
    crisis_escalations: int
    off_topic_redirects: int
    offensive_content_blocks: int
    languages_detected: List[str]
    user_name: Optional[str]
    first_seen: Optional[str]
    last_seen: Optional[str]
    name_learned: bool


class SessionCreateRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="Optional user identifier")


class SessionCreateResponse(BaseModel):
    session_id: str
    user_id: Optional[str]
    created_at: str
    message: str = "Session created successfully"


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: str


class HealthCheckResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: str
    services: Dict[str, str]

# ============================================================================
# Session Store
# ============================================================================

_session_store: Dict[str, MindSpaceChatbot] = {}
_session_timestamps: Dict[str, datetime] = {}
SESSION_TIMEOUT_HOURS = 24

# ============================================================================
# FastAPI Application (with Lifespan)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 MindSpace Chatbot API starting...")
    logger.info("📚 Documentation available at /docs")
    logger.info("🔍 Health check available at /health")
    logger.info(f"📊 Max sessions: {len(_session_store)}")
    yield
    logger.info("👋 MindSpace Chatbot API shutting down...")
    for session_id, chatbot in _session_store.items():
        try:
            if hasattr(chatbot, 'memory') and chatbot.memory:
                chatbot.memory._save_memory()
                logger.info(f"💾 Saved session: {session_id}")
        except Exception as e:
            logger.error(f"❌ Error saving session {session_id}: {e}")

app = FastAPI(
    title="MindSpace Chatbot API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware - Production ready
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
is_wildcard = ALLOWED_ORIGINS == ["*"] or "*" in ALLOWED_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False if is_wildcard else True,  # Credentials must be false for wildcard *
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    max_age=86400,
)


def cleanup_expired_sessions():
    """Clean up expired sessions."""
    now = datetime.now()
    expired = []
    for session_id, last_active in _session_timestamps.items():
        if now - last_active > timedelta(hours=SESSION_TIMEOUT_HOURS):
            expired.append(session_id)
    
    for session_id in expired:
        if session_id in _session_store:
            del _session_store[session_id]
        if session_id in _session_timestamps:
            del _session_timestamps[session_id]
    
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired sessions")


def get_or_create_chatbot(session_id: Optional[str] = None, user_id: Optional[str] = None, client_ip: Optional[str] = None, user_name: Optional[str] = None) -> MindSpaceChatbot:
    """Get or create a chatbot instance for a session."""
    # Cleanup expired sessions periodically
    cleanup_expired_sessions()
    
    # 1. If user_id is provided and session_id is not, query SQLite for existing session
    if user_id and not session_id:
        from db import Session, ChatSession
        try:
            with Session() as db_session:
                db_sess = db_session.query(ChatSession).filter_by(user_id=user_id).first()
                if db_sess:
                    session_id = db_sess.session_id
        except Exception as e:
            logger.error(f"Error querying session for user_id {user_id}: {e}")
    
    # 2. If session_id is provided, try loading from cache or SQLite
    if session_id:
        if session_id in _session_store:
            _session_timestamps[session_id] = datetime.now()
            chatbot = _session_store[session_id]
            if user_name and not chatbot.memory.get_user_name():
                chatbot.memory.set_user_name(user_name)
            return chatbot
        
        # Cache miss: check SQLite
        from db import Session, ChatSession
        try:
            with Session() as db_session:
                db_sess = db_session.query(ChatSession).filter_by(session_id=session_id).first()
                if db_sess:
                    chatbot = MindSpaceChatbot(session_id)
                    if user_name and not chatbot.memory.get_user_name():
                        chatbot.memory.set_user_name(user_name)
                    if user_id and db_sess.user_id != user_id:
                        db_sess.user_id = user_id
                        db_session.commit()
                    _session_store[session_id] = chatbot
                    _session_timestamps[session_id] = datetime.now()
                    return chatbot
        except Exception as e:
            logger.error(f"Error restoring session {session_id} from SQLite: {e}")

    # 3. Create new session
    if not session_id:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    chatbot = MindSpaceChatbot(session_id)
    
    # Initialize/update fields in SQLite
    from db import Session, ChatSession
    try:
        with Session() as db_session:
            db_sess = db_session.query(ChatSession).filter_by(session_id=session_id).first()
            if db_sess:
                db_sess.user_id = user_id
                if user_name:
                    db_sess.user_name = user_name
                db_session.commit()
    except Exception as e:
        logger.error(f"Error saving new session {session_id} details: {e}")
        
    if user_name:
        chatbot.memory.set_user_name(user_name)
        
    _session_store[session_id] = chatbot
    _session_timestamps[session_id] = datetime.now()
    
    return chatbot

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/", response_model=Dict[str, str])
async def root():
    return {
        "name": "MindSpace Chatbot API",
        "version": "1.0.0",
        "status": "running",
        "documentation": "/docs",
        "health": "/health"
    }


@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    return HealthCheckResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now().isoformat(),
        services={
            "chatbot": "active",
            "memory": "active",
            "api": "active",
            "sessions": str(len(_session_store))
        }
    )


@app.post("/api/session", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_api_key)])
def create_session(request: SessionCreateRequest):
    try:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        chatbot = MindSpaceChatbot(session_id)
        
        from db import Session, ChatSession
        with Session() as db_session:
            db_sess = db_session.query(ChatSession).filter_by(session_id=session_id).first()
            if db_sess and request.user_id:
                db_sess.user_id = request.user_id
                db_session.commit()
                
        _session_store[session_id] = chatbot
        _session_timestamps[session_id] = datetime.now()
        
        return SessionCreateResponse(
            session_id=session_id,
            user_id=request.user_id,
            created_at=datetime.now().isoformat(),
            message="Session created successfully"
        )
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}"
        )


@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
def chat(request: ChatRequest, req: Request):
    try:
        # Rate limiting
        client_ip = req.client.host if req.client else "unknown"
        if not rate_limiter.check(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please wait a moment before sending more messages."
            )
        
        # Validate message
        if not request.message or not request.message.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message cannot be empty"
            )
        
        # Get or create chatbot instance
        chatbot = get_or_create_chatbot(request.session_id, request.user_id, client_ip, request.user_name)
        
        # Get stats before response generation to identify triggers
        stats_before = chatbot.get_stats()
        
        # Get response (handles translation, domain check, crisis, and offensive content)
        response_text = chatbot.get_response(request.message)
        
        # Get stats after response generation
        stats_after = chatbot.get_stats()
        
        # Detect if safety triggers were fired based on statistics changes
        is_offensive = stats_after.get("offensive_content_blocks", 0) > stats_before.get("offensive_content_blocks", 0)
        is_crisis = stats_after.get("crisis_escalations", 0) > stats_before.get("crisis_escalations", 0)
        
        # Detect language
        language = detect_language(request.message)
        
        # Get user name if known
        user_name = chatbot.memory.get_user_name()
        
        # Generate message ID
        message_id = f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        return ChatResponse(
            response=response_text,
            session_id=chatbot.session_id,
            message_id=message_id,
            timestamp=datetime.now().isoformat(),
            is_crisis=is_crisis,
            is_offensive=is_offensive,
            language=language,
            user_name=user_name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process message: {str(e)}"
        )


@app.get("/api/session/{session_id}/stats", response_model=SessionStats, dependencies=[Depends(verify_api_key)])
def get_session_stats(session_id: str):
    try:
        if session_id not in _session_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        chatbot = _session_store[session_id]
        stats = chatbot.get_stats()
        user_info = chatbot.memory.get_user_info()
        
        return SessionStats(
            session_id=session_id,
            total_messages=stats.get("total_messages", 0),
            history_length=stats.get("history_length", 0),
            crisis_escalations=stats.get("crisis_escalations", 0),
            off_topic_redirects=stats.get("off_topic_redirects", 0),
            offensive_content_blocks=stats.get("offensive_content_blocks", 0),
            languages_detected=stats.get("languages_detected", []),
            user_name=stats.get("user_name"),
            first_seen=user_info.get("first_seen"),
            last_seen=user_info.get("last_seen"),
            name_learned=stats.get("name_learned", False)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session stats: {str(e)}"
        )


@app.delete("/api/session/{session_id}/clear", dependencies=[Depends(verify_api_key)])
def clear_session_memory(session_id: str):
    try:
        if session_id not in _session_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        chatbot = _session_store[session_id]
        chatbot.clear_memory()
        
        return {
            "status": "success",
            "message": f"Memory cleared for session {session_id}",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error clearing session memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear session memory: {str(e)}"
        )


@app.delete("/api/session/{session_id}/reset", dependencies=[Depends(verify_api_key)])
def reset_session(session_id: str):
    try:
        if session_id not in _session_store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        chatbot = _session_store[session_id]
        chatbot.reset_all()
        
        return {
            "status": "success",
            "message": f"Session {session_id} reset completely",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset session: {str(e)}"
        )


@app.delete("/api/session/{session_id}", dependencies=[Depends(verify_api_key)])
def delete_session(session_id: str):
    try:
        # We also need to delete from the SQLite database
        from conversation_memory import delete_memory
        delete_memory(session_id)
        
        if session_id in _session_store:
            del _session_store[session_id]
        if session_id in _session_timestamps:
            del _session_timestamps[session_id]
        
        return {
            "status": "success",
            "message": f"Session {session_id} deleted successfully",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete session: {str(e)}"
        )


@app.get("/api/sessions", dependencies=[Depends(verify_api_key)])
def list_sessions():
    try:
        sessions = []
        for session_id, chatbot in _session_store.items():
            stats = chatbot.get_stats()
            user_name = stats.get("user_name")
            user_info = chatbot.memory.get_user_info()
            sessions.append({
                "session_id": session_id,
                "user_name": user_name,
                "total_messages": stats.get("total_messages", 0),
                "created_at": user_info.get("first_seen"),
                "last_active": user_info.get("last_seen")
            })
        
        return {
            "total_sessions": len(sessions),
            "active_sessions": len([s for s in sessions if s.get("last_active")]),
            "sessions": sessions,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list sessions: {str(e)}"
        )

# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            detail=str(exc.detail),
            timestamp=datetime.now().isoformat()
        ).model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc),
            timestamp=datetime.now().isoformat()
        ).model_dump()
    )

# ============================================================================
# End of Event Definitions
# ============================================================================


# ============================================================================
# Main entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    from config import API_HOST, API_PORT, API_RELOAD, API_WORKERS
    
    print("=" * 60)
    print("🌟 MindSpace Chatbot API Server")
    print("=" * 60)
    print("🚀 Starting server...")
    print(f"📚 API Documentation: http://localhost:{API_PORT}/docs")
    print(f"🔍 Health Check: http://localhost:{API_PORT}/health")
    print(f"📨 Chat Endpoint: POST http://localhost:{API_PORT}/api/chat")
    print("=" * 60)
    
    # Uvicorn only supports workers > 1 if reload is False
    workers = 1 if API_RELOAD else API_WORKERS
    
    uvicorn.run(
        "api:app",
        host=API_HOST,
        port=API_PORT,
        reload=API_RELOAD,
        workers=workers,
        log_level="info"
    )