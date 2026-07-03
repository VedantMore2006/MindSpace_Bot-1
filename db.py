from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os

DB_PATH = os.getenv("DB_PATH", "/app/data/mindspace.db")

# Ensure the parent directory of the database exists
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)

class ChatSession(Base):
    __tablename__ = "sessions"
    session_id   = Column(String, primary_key=True)
    user_id      = Column(String, index=True)
    user_name    = Column(String)
    created_at   = Column(DateTime, default=datetime.now)
    last_seen    = Column(DateTime, default=datetime.now)
    stats_json   = Column(Text, default="{}")  # Stores serialized stats dict

class Message(Base):
    __tablename__ = "messages"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)
    role       = Column(String)   # "user" or "assistant"
    content    = Column(Text)
    timestamp  = Column(DateTime, default=datetime.now)

Base.metadata.create_all(engine)
