from pydantic import BaseModel, ConfigDict
from typing import Optional

class UserBase(BaseModel):
    """Base schema for shared user attributes."""
    email: str

class UserCreate(UserBase):
    """Schema used during user creation."""
    credentials: Optional[str] = None

class UserResponse(UserBase):
    """Schema returned in API responses, including database IDs."""
    id: int

    model_config = ConfigDict(from_attributes=True)
