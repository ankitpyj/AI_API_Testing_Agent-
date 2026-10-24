from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field
from typing import List
from typing import Literal

app = FastAPI(
    title="Target User API",
    description="API used for testing the AI API Testing Agent",
    version="1.0.0"
)


# -----------------------------
# Data Models
# -----------------------------

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    age: int = Field(ge=0, le=120)


class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    age: int | None = Field(default=None, ge=0, le=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    
class HealthResponse(BaseModel):
    status: Literal["ok"]


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    age: int


class UsersResponse(BaseModel):
    users: List[UserResponse]


class LoginResponse(BaseModel):
    message: str
    user_id: int


class MessageResponse(BaseModel):
    message: str


# -----------------------------
# Temporary In-Memory Database
# -----------------------------

INITIAL_USERS = [
    {
        "id": 1,
        "name": "Ankit",
        "email": "ankit@example.com",
        "age": 21
    },
    {
        "id": 2,
        "name": "Rahul",
        "email": "rahul@example.com",
        "age": 22
    }
]

users = [user.copy() for user in INITIAL_USERS]

# -----------------------------
# RESET TEST DATA
# -----------------------------

@app.post("/reset",include_in_schema=False)
def reset_users():

    global users

    users = [user.copy() for user in INITIAL_USERS]

    return {
        "message": "Test data reset successfully",
        "users": users
    }

# -----------------------------
# Root
# -----------------------------

@app.get(
    "/",
    response_model=MessageResponse
)
def root():
    return {"message": "Target User API is running"}

# -----------------------------
# Health Check
# -----------------------------

@app.get(
    "/health",
    response_model=HealthResponse
)
def health():
    return {"status": "ok"}


# -----------------------------
# GET ALL USERS
# -----------------------------

@app.get(
    "/users",
    response_model=UsersResponse
)
def get_users():
    return {"users": users}


# -----------------------------
# CREATE USER
# -----------------------------

@app.post(
    "/users",
    status_code=201,
    response_model=UserResponse
)
def create_user(user: UserCreate):

    new_user = {
        "id": len(users) + 1,
        "name": user.name,
        "email": user.email,
        "age": user.age
    }

    users.append(new_user)

    return new_user


# -----------------------------
# GET USER BY ID
# -----------------------------

@app.get(
    "/users/{user_id}",
    response_model=UserResponse
)
def get_user(user_id: int):

    for user in users:
        if user["id"] == user_id:
            return user

    raise HTTPException(
        status_code=404,
        detail="User not found"
    )


# -----------------------------
# UPDATE USER
# -----------------------------

@app.put(
    "/users/{user_id}",
    response_model=UserResponse
)
def update_user(user_id: int, user_data: UserUpdate):

    for user in users:

        if user["id"] == user_id:

            if user_data.name is not None:
                user["name"] = user_data.name

            if user_data.email is not None:
                user["email"] = user_data.email

            if user_data.age is not None:
                user["age"] = user_data.age

            return user

    raise HTTPException(
        status_code=404,
        detail="User not found"
    )


# -----------------------------
# DELETE USER
# -----------------------------

@app.delete(
    "/users/{user_id}",
    response_model=MessageResponse
)
def delete_user(user_id: int):

    for user in users:

        if user["id"] == user_id:

            users.remove(user)

            return {
                "message": "User deleted successfully"
            }

    raise HTTPException(
        status_code=404,
        detail="User not found"
    )


# -----------------------------
# LOGIN
# -----------------------------

@app.post(
    "/login",
    response_model=LoginResponse
)
def login(credentials: LoginRequest):

    for user in users:

        if user["email"] == credentials.email:

            return {
                "message": "Login successful",
                "user_id": user["id"]
            }

    raise HTTPException(
        status_code=401,
        detail="Invalid credentials"
    )