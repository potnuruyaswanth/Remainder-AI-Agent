import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta

from app.database import Base
from app.models.user import User
from app.models.task import Task
from app.models.email import ProcessedEmail

# Set up an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def fixture_db_session():
    """Provides a clean in-memory database session for each test case."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create all tables in the temporary database
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_user_crud(db_session):
    """Tests creating, reading, updating, and deleting a User."""
    # 1. Create (Insert)
    new_user = User(email="alice@example.com", credentials="encrypted-key-json-string")
    db_session.add(new_user)
    db_session.commit()
    
    # 2. Read (Select)
    user = db_session.query(User).filter_by(email="alice@example.com").first()
    assert user is not None
    assert user.id is not None
    assert user.credentials == "encrypted-key-json-string"
    
    # 3. Update
    user.credentials = "updated-credentials"
    db_session.commit()
    
    updated_user = db_session.query(User).filter_by(id=user.id).first()
    assert updated_user.credentials == "updated-credentials"
    
    # 4. Delete
    db_session.delete(updated_user)
    db_session.commit()
    
    deleted_user = db_session.query(User).filter_by(email="alice@example.com").first()
    assert deleted_user is None

def test_task_crud_and_relationship(db_session):
    """Tests Task CRUD operations and checks its relationship to User."""
    # Create user first
    user = User(email="bob@example.com", credentials="dummy")
    db_session.add(user)
    db_session.commit()

    # 1. Create Task (Verify Default Values)
    due_date = datetime.utcnow() + timedelta(days=2)
    task = Task(
        user_id=user.id,
        title="Finish Architecture Homework",
        description="Must complete the SDD diagram",
        deadline=due_date
    )
    db_session.add(task)
    db_session.commit()

    # 2. Read Task & Verify Relationship
    saved_task = db_session.query(Task).filter_by(title="Finish Architecture Homework").first()
    assert saved_task is not None
    assert saved_task.user_id == user.id
    assert saved_task.owner == user
    assert saved_task.completed is False  # default status
    assert saved_task.priority == "Medium"  # default priority
    assert saved_task.google_task_id is None
    assert saved_task.sync_status == "pending"
    assert saved_task.last_synced_at is None
    
    # Check User -> Task relationship linkage
    assert len(user.tasks) == 1
    assert user.tasks[0] == saved_task

    # 3. Update Task (Sync Fields)
    saved_task.completed = True
    saved_task.priority = "High"
    saved_task.google_task_id = "gtask-12345"
    db_session.commit()

    updated_task = db_session.query(Task).filter_by(id=saved_task.id).first()
    assert updated_task.completed is True
    assert updated_task.priority == "High"
    assert updated_task.google_task_id == "gtask-12345"

    # 4. Delete Task
    db_session.delete(updated_task)
    db_session.commit()
    
    assert db_session.query(Task).filter_by(id=saved_task.id).first() is None
    assert len(user.tasks) == 0

def test_processed_email_crud(db_session):
    """Tests ProcessedEmail CRUD operations and uniqueness constraint."""
    user = User(email="carol@example.com", credentials="key")
    db_session.add(user)
    db_session.commit()

    # 1. Create
    email_log = ProcessedEmail(
        user_id=user.id,
        gmail_id="msg-abc-123",
        subject="Project Update",
        snippet="Please see the attached reports for details."
    )
    db_session.add(email_log)
    db_session.commit()

    # 2. Read
    saved_log = db_session.query(ProcessedEmail).filter_by(gmail_id="msg-abc-123").first()
    assert saved_log is not None
    assert saved_log.user == user
    assert saved_log.subject == "Project Update"
    assert len(user.emails) == 1

    # 3. Constraint Check (Uniqueness on gmail_id)
    from sqlalchemy.exc import IntegrityError
    duplicate_log = ProcessedEmail(
        user_id=user.id,
        gmail_id="msg-abc-123",  # same ID!
        subject="Another subject"
    )
    db_session.add(duplicate_log)
    with pytest.raises(IntegrityError):
        db_session.commit()

def test_cascade_delete(db_session):
    """Tests that deleting a User cascades and deletes all associated Tasks and ProcessedEmails."""
    user = User(email="dan@example.com", credentials="key")
    db_session.add(user)
    db_session.commit()

    task1 = Task(user_id=user.id, title="Task 1")
    task2 = Task(user_id=user.id, title="Task 2")
    email1 = ProcessedEmail(user_id=user.id, gmail_id="gmail-1", subject="Subject 1")
    
    db_session.add_all([task1, task2, email1])
    db_session.commit()

    # Verify setup
    assert db_session.query(Task).filter_by(user_id=user.id).count() == 2
    assert db_session.query(ProcessedEmail).filter_by(user_id=user.id).count() == 1

    # Delete user
    db_session.delete(user)
    db_session.commit()

    # Assert cascade deleted
    assert db_session.query(Task).filter_by(user_id=user.id).count() == 0
    assert db_session.query(ProcessedEmail).filter_by(user_id=user.id).count() == 0
