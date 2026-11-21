import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from pathlib import Path

import bcrypt
import jwt
from dotenv import load_dotenv
from pydantic import BaseModel, EmailStr, Field
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

try:
    from agent_backend import db_operations
except ImportError:
    import db_operations

# Load environment configuration
load_dotenv(Path(__file__).parent / ".env")

JWT_SECRET = os.getenv(
    "JWT_SECRET",
    "super-secret-jwt-key-for-ai-api-testing-agent-change-in-prod"
)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))


# ==========================================
# Password Hashing Utilities (bcrypt)
# ==========================================

def hash_password(password: str) -> str:
    """
    Hash a password securely using bcrypt with auto-generated salt.
    Truncates password to 72 bytes to conform with bcrypt specifications.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a bcrypt password hash.
    Safe against timing attacks.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


# ==========================================
# JWT Utilities (PyJWT)
# ==========================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Generate a signed JWT access token with expiration and issue time.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=JWT_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now
    })
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.
    Validates cryptographic signature, expiry, and format.
    Raises jwt.ExpiredSignatureError or jwt.PyJWTError on failure.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ==========================================
# Request / Response Models
# ==========================================

class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    role: str = "user"
    plan: str = "internal_demo"
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None


class AuthResponseData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ==========================================
# FastAPI Authentication Dependency
# ==========================================

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> dict:
    """
    FastAPI dependency to extract and verify the current authenticated user.
    Reads Authorization: Bearer <token>, validates JWT signature/expiration,
    and fetches user details from the database.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"}
            )
        user_id = int(user_id_str)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user = db_operations.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Ensure password hash is never present in current_user context
    user.pop("password_hash", None)
    return user


def get_current_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency to verify that the current authenticated user has administrator privileges.
    Requires verified JWT and role == 'admin'.
    Raises 403 Forbidden if user is not an administrator.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required for this operation"
        )
    return current_user
