from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class Task(Base):
    """
    Represents an actionable task extracted from an email or created manually.
    
    Tied to a User via foreign key. Connects to Google Tasks via the google_task_id field.
    """
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    
    # Task deadline date and time
    deadline = Column(DateTime, nullable=True, index=True)
    
    # Task priority: High, Medium, Low
    priority = Column(String, default="Medium", nullable=False)
    
    # Completion status
    completed = Column(Boolean, default=False, nullable=False, index=True)
    
    # Tracking timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Google Task API ID, used for keeping state synced with Google Tasks service
    google_task_id = Column(String, unique=True, index=True, nullable=True)
    sync_status = Column(String, default="pending", nullable=False, index=True)
    last_synced_at = Column(DateTime, nullable=True)

    # Relationships
    owner = relationship("User", back_populates="tasks")

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title} completed={self.completed}>"
