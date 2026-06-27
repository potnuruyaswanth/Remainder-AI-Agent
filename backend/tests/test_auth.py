import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.user import User
from app.services.auth_service import AuthService, TokenEncryption
from app.routers.auth import router as auth_router, get_current_user
from app.schemas.user import UserResponse

# SQLite in-memory DB for auth tests
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="auth_db")
def fixture_auth_db():
    """Provides an isolated database session for testing auth logic."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def fixture_client(auth_db):
    """Provides a TestClient for testing auth router endpoints."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/auth")

    # Override get_db dependency
    def override_get_db():
        try:
            yield auth_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_token_encryption():
    """Tests that TokenEncryption correctly encrypts and decrypts text strings."""
    encryptor = TokenEncryption()
    raw_text = "my-super-secret-oauth-refresh-token-123"
    
    cipher_text = encryptor.encrypt(raw_text)
    assert cipher_text != raw_text
    
    decrypted_text = encryptor.decrypt(cipher_text)
    assert decrypted_text == raw_text

    # Verify that attempting to decrypt invalid text raises an exception
    with pytest.raises(Exception):
        encryptor.decrypt("invalid-cipher-text")


def test_auth_service_save_credentials(auth_db):
    """Tests saving credentials for new and existing users in the database."""
    service = AuthService(auth_db)
    email = "testuser@gmail.com"
    creds_dict = {"token": "access", "refresh_token": "refresh"}

    # 1. Save new credentials
    user = service.save_user_credentials(email, creds_dict)
    assert user.email == email
    assert user.credentials is not None

    # Retrieve and decrypt
    db_user = auth_db.query(User).filter_by(email=email).first()
    decrypted = service.encryption.decrypt(db_user.credentials)
    assert json.loads(decrypted) == creds_dict

    # 2. Update existing credentials
    new_creds_dict = {"token": "new-access", "refresh_token": "new-refresh"}
    updated_user = service.save_user_credentials(email, new_creds_dict)
    assert updated_user.id == user.id  # Must update existing record instead of creating new

    db_user = auth_db.query(User).filter_by(email=email).first()
    decrypted = service.encryption.decrypt(db_user.credentials)
    assert json.loads(decrypted) == new_creds_dict


@patch("app.services.auth_service.Credentials")
@patch("app.services.auth_service.Request")
def test_auth_service_get_and_refresh_credentials(mock_request, mock_credentials_class, auth_db):
    """Tests getting and automatically refreshing user credentials."""
    service = AuthService(auth_db)
    email = "refreshuser@gmail.com"
    creds_dict = {
        "token": "old-access-token",
        "refresh_token": "refresh-token",
        "token_uri": "http://token-uri",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scopes": []
    }
    
    # Pre-save credentials in DB
    user = service.save_user_credentials(email, creds_dict)

    # Configure mocked Credentials instance
    mock_creds_instance = MagicMock()
    mock_creds_instance.expired = True  # Force expiration triggers refresh
    mock_creds_instance.refresh_token = "refresh-token"
    mock_creds_instance.token = "new-refreshed-access-token"
    mock_creds_instance.token_uri = "http://token-uri"
    mock_creds_instance.client_id = "client-id"
    mock_creds_instance.client_secret = "client-secret"
    mock_creds_instance.scopes = []

    mock_credentials_class.return_value = mock_creds_instance

    # Fetch credentials (this should trigger decrypt -> Credentials instantiate -> refresh() -> save_user_credentials())
    retrieved_creds = service.get_user_credentials(user.id)
    
    # Assert refresh calls were made
    mock_creds_instance.refresh.assert_called_once()
    assert retrieved_creds.token == "new-refreshed-access-token"

    # Verify that refreshed tokens are updated in DB
    db_user = auth_db.query(User).filter_by(id=user.id).first()
    decrypted_str = service.encryption.decrypt(db_user.credentials)
    updated_dict = json.loads(decrypted_str)
    assert updated_dict["token"] == "new-refreshed-access-token"


def test_login_redirect(client):
    """Tests that the /login endpoint redirects to Google's authorization URL."""
    with patch("app.services.auth_service.Flow") as MockFlow:
        mock_flow_instance = MagicMock()
        mock_flow_instance.authorization_url.return_value = ("https://accounts.google.com/test-oauth-url", "state123")
        MockFlow.from_client_config.return_value = mock_flow_instance

        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 307  # FastAPI redirects responses
        assert response.headers["location"] == "https://accounts.google.com/test-oauth-url"


@pytest.mark.anyio
@patch("httpx.AsyncClient.get")
def test_callback_flow(mock_http_get, client, auth_db):
    """Tests the full OAuth callback flow: exchange, userinfo retrieval, DB save, and cookie redirect."""
    with patch("app.services.auth_service.Flow") as MockFlow:
        # Mock Google Flow
        mock_flow_instance = MagicMock()
        mock_creds = MagicMock()
        mock_creds.token = "mock-access-token"
        mock_creds.refresh_token = "mock-refresh-token"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "client-id"
        mock_creds.client_secret = "client-secret"
        mock_creds.scopes = ["scope1"]
        
        mock_flow_instance.credentials = mock_creds
        MockFlow.from_client_config.return_value = mock_flow_instance

        # Mock User info HTTP response
        mock_response = MagicMock()
        mock_response.json.return_value = {"email": "oauthuser@gmail.com"}
        mock_response.raise_for_status = MagicMock()
        mock_http_get.return_value = mock_response

        # Execute callback GET request
        response = client.get("/auth/callback?code=oauthcode123", follow_redirects=False)
        
        # Verify redirect
        assert response.status_code == 307
        assert response.headers["location"] == "http://localhost:5173"
        
        # Verify cookie is set
        assert "session_token" in response.cookies
        
        # Verify user created in DB
        db_user = auth_db.query(User).filter_by(email="oauthuser@gmail.com").first()
        assert db_user is not None
        
        # Verify cookie payload matches user ID
        encryption = TokenEncryption()
        decrypted_user_id = int(encryption.decrypt(response.cookies["session_token"]))
        assert decrypted_user_id == db_user.id


def test_logout(client, auth_db):
    """Tests that logging out deletes the session token cookie."""
    # Create a user to authenticate
    user = User(email="active@example.com", credentials="key")
    auth_db.add(user)
    auth_db.commit()

    encryption = TokenEncryption()
    session_token = encryption.encrypt(str(user.id))
    client.cookies.set("session_token", session_token)

    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "logged_out"}
    
    # Cookie should be cleared
    assert response.cookies.get("session_token") is None
