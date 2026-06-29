import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.services.auth_service import AuthService, TokenEncryption
from app.schemas.user import UserResponse
from app.models.user import User
from app.utils.logger import logger

router = APIRouter()

# Dependency to get current user based on the session cookie
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Validates the session cookie and returns the authenticated User.
    
    Raises 401 Unauthorized if the session is invalid or expired.
    """
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    try:
        encryption = TokenEncryption()
        decrypted_payload = encryption.decrypt(session_token)
        user_id = int(decrypted_payload)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token"
        )
        
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    return user


@router.get("/login")
def login(db: Session = Depends(get_db)):
    """
    Initiates the Google OAuth 2.0 flow.
    
    Generates the Google OAuth authorization URL and redirects the user's browser.
    """
    auth_service = AuthService(db)
    flow = auth_service.get_google_flow()
    
    # Enable offline access to get the Refresh Token
    # prompt='consent' forces Google to show the consent screen so we always get a refresh token
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent"
    )
    
    logger.info("Redirecting user to Google OAuth consent page.")
    return RedirectResponse(url=authorization_url)


@router.get("/callback")
async def callback(request: Request, code: str, db: Session = Depends(get_db)):
    """
    Handles the Google OAuth redirect callback.
    
    Exchanges the authorization code for access and refresh tokens,
    retrieves user profile info from Google, saves credentials in the database,
    and sets an encrypted session cookie.
    """
    auth_service = AuthService(db)
    flow = auth_service.get_google_flow(state=request.query_params.get("state"))
    
    # 1. Exchange authorization code for tokens
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.error("Failed to fetch token from Google OAuth code", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth exchange failed: {e}"
        )
        
    creds = flow.credentials
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to obtain credentials"
        )

    # 2. Fetch user profile from Google UserInfo endpoint
    try:
        async with httpx.AsyncClient() as client:
            user_info_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"}
            )
            user_info_resp.raise_for_status()
            user_info = user_info_resp.json()
    except Exception as e:
        logger.error("Failed to fetch user info from Google API", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch user info from Google"
        )

    email = user_info.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User email not returned by Google"
        )

    # 3. Encrypt and save tokens in DB
    credentials_dict = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes
    }
    
    try:
        user = auth_service.save_user_credentials(email, credentials_dict)
    except Exception as e:
        logger.error(f"Error saving user credentials in DB for {email}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist user credentials"
        )

    # 4. Generate encrypted session token (using user's DB ID)
    encryption = TokenEncryption()
    session_token = encryption.encrypt(str(user.id))

    # 5. Redirect to frontend with the session cookie set
    # Using secure, HttpOnly cookie settings
    redirect_response = RedirectResponse(url=settings.FRONTEND_URL)
    redirect_response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        max_age=3600 * 24 * 7,  # 7 days
        samesite="lax",
        secure=False  # Set to True in production (HTTPS only)
    )
    
    logger.info(f"User {email} successfully authenticated and logged in.")
    return redirect_response


@router.api_route("/logout", methods=["GET", "POST"])
def logout(current_user: User = Depends(get_current_user)):
    """Logs out the user by clearing the session token cookie."""
    logger.info(f"User logged out.")
    response = Response(content='{"status":"logged_out"}', media_type="application/json")
    response.delete_cookie("session_token")
    return response


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Returns the profile of the currently logged-in user."""
    return current_user
