import json
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
except ImportError:  # pragma: no cover - exercised only when optional deps are missing
    Request = object

    class Credentials:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                "Google authentication dependencies are not installed. "
                "Install google-auth and google-auth-oauthlib to use OAuth features."
            )

    class Flow:  # type: ignore[override]
        @classmethod
        def from_client_config(cls, *args, **kwargs):
            raise RuntimeError(
                "Google OAuth dependencies are not installed. "
                "Install google-auth-oauthlib to start the OAuth flow."
            )

from app.config import settings
from app.models.user import User
from app.utils.logger import logger

class TokenEncryption:
    """Handles secure encryption and decryption of OAuth tokens at rest."""

    def __init__(self) -> None:
        if not settings.ENCRYPTION_KEY:
            raise ValueError("ENCRYPTION_KEY environment variable is not set!")
        try:
            self.fernet = Fernet(settings.ENCRYPTION_KEY.encode())
        except Exception as e:
            logger.error("Failed to initialize Fernet with ENCRYPTION_KEY", exc_info=True)
            raise ValueError(f"Invalid ENCRYPTION_KEY: {e}")

    def encrypt(self, plain_text: str) -> str:
        """Encrypts a plain text string using Fernet symmetric encryption."""
        return self.fernet.encrypt(plain_text.encode()).decode()

    def decrypt(self, cipher_text: str) -> str:
        """Decrypts a Fernet cipher text back to a plain text string."""
        return self.fernet.decrypt(cipher_text.encode()).decode()


class AuthService:
    """Manages User Authentication, Google OAuth 2.0 flow, and Credential Refreshing."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.encryption = TokenEncryption()

    def get_google_flow(self, state: Optional[str] = None) -> Flow:
        """
        Creates a Flow instance configured with client ID, secret, scopes, and redirect URI.
        
        Parameters:
            state (str, optional): The OAuth state parameter to protect against CSRF.
            
        Returns:
            google_auth_oauthlib.flow.Flow: Configured Google OAuth flow runner.
        """
        client_config = {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            }
        }
        
        flow = Flow.from_client_config(
            client_config=client_config,
            scopes=settings.GOOGLE_SCOPES,
            state=state
        )
        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
        return flow

    def save_user_credentials(self, email: str, credentials_dict: Dict[str, Any]) -> User:
        """
        Saves or updates user OAuth credentials in the database.
        
        Encrypts the credentials before storage.
        
        Parameters:
            email (str): The email address of the authenticated user.
            credentials_dict (dict): The dictionary containing OAuth tokens (refresh, access, etc.).
            
        Returns:
            User: The saved or updated User database model instance.
        """
        serialized_creds = json.dumps(credentials_dict)
        encrypted_creds = self.encryption.encrypt(serialized_creds)
        
        # Check if user already exists
        user = self.db.query(User).filter_by(email=email).first()
        if user:
            logger.info(f"Updating credentials for existing user: {email}")
            user.credentials = encrypted_creds
        else:
            logger.info(f"Creating new user record for: {email}")
            user = User(email=email, credentials=encrypted_creds)
            self.db.add(user)
            
        try:
            self.db.commit()
            self.db.refresh(user)
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to save credentials for user {email}", exc_info=True)
            raise e
            
        return user

    def get_user_credentials(self, user_id: int) -> Optional[Credentials]:
        """
        Retrieves, decrypts, and instantiates the Google Credentials object for a user.
        
        Refreshes the access token automatically if it has expired.
        
        Parameters:
            user_id (int): The database primary key of the User.
            
        Returns:
            google.oauth2.credentials.Credentials: Instantiated Google Credentials object,
            or None if the user does not exist or has no credentials.
        """
        user = self.db.query(User).filter_by(id=user_id).first()
        if not user or not user.credentials:
            logger.warning(f"No credentials found for user ID: {user_id}")
            return None

        # Decrypt and load credentials dictionary
        try:
            decrypted_json = self.encryption.decrypt(user.credentials)
            creds_data = json.loads(decrypted_json)
        except Exception as e:
            logger.error(f"Failed to decrypt credentials for user ID {user_id}", exc_info=True)
            return None

        # Instantiate Google Credentials object
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
            scopes=creds_data.get("scopes")
        )

        # Automatically refresh if expired
        if creds.expired and creds.refresh_token:
            logger.info(f"Refreshing expired Google Access Token for user ID: {user_id}")
            try:
                creds.refresh(Request())
                # Re-save updated credentials (the access token changed, and expiry updated)
                self.save_user_credentials(user.email, {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": creds.scopes
                })
            except Exception as e:
                logger.error(f"Failed to refresh access token for user ID {user_id}", exc_info=True)
                # Propagate or return current stale creds (caller must handle Auth exceptions)
                
        return creds
