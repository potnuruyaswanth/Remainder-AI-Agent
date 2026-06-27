from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    """
    Represents a user in the system.
    
    This model stores the user's identity and encrypted OAuth credentials 
    used to access Google APIs (Gmail and Google Tasks) in the background.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    
    # User's primary email address (e.g. from Google profile), must be unique
    email = Column(String, unique=True, index=True, nullable=False)
    
    # Encrypted JSON string storing OAuth2 credentials (access_token, refresh_token, etc.)
    credentials = Column(Text, nullable=True)

    # Relationships
    # back_populates connects this property to the corresponding property in child models
    # cascade="all, delete-orphan" ensures deleting a user removes all their tasks/emails from the DB
    tasks = relationship("Task", back_populates="owner", cascade="all, delete-orphan")
    emails = relationship("ProcessedEmail", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"
