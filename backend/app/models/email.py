from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class ProcessedEmail(Base):
    """
    Represents an email that has already been scanned by the EmailTaskAgent.
    
    This model acts as a history log and deduplication index, ensuring that 
    the agent only processes new emails.
    """
    __tablename__ = "processed_emails"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Unique Gmail API Message ID
    gmail_id = Column(String, unique=True, index=True, nullable=False)
    
    # Cached email metadata for rendering in dashboard/emails list
    subject = Column(String, nullable=True)
    snippet = Column(Text, nullable=True)
    
    # Timestamp of when the agent successfully scanned this email
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="emails")

    def __repr__(self) -> str:
        return f"<ProcessedEmail id={self.id} gmail_id={self.gmail_id}>"
