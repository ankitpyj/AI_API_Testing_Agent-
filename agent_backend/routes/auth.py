from fastapi import APIRouter, Depends, HTTPException, status

try:
    from agent_backend import auth
    from agent_backend import db_operations
    from agent_backend import plans
    from agent_backend import usage_service
except ImportError:
    import auth
    import db_operations
    import plans
    import usage_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(request: auth.RegisterRequest):
    """
    Register a new user account.
    Validates input fields, verifies matching passwords, ensures email uniqueness,
    hashes the password using bcrypt, and issues a JWT access token.
    """
    if request.password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )

    # Check if email is already registered
    existing_user = db_operations.get_user_by_email(request.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered"
        )

    # Hash password securely with bcrypt
    password_hash = auth.hash_password(request.password)

    # Save to database (public registration always defaults to role='user' and default plan)
    default_plan = plans.get_default_registration_plan()
    user = db_operations.create_user(
        full_name=request.full_name,
        email=request.email,
        password_hash=password_hash,
        role="user",
        plan=default_plan
    )

    # Issue JWT token
    access_token = auth.create_access_token(
        data={
            "sub": str(user["id"]),
            "email": user["email"],
            "name": user["full_name"]
        }
    )

    return {
        "status": "success",
        "data": {
            "access_token": access_token,
            "token_type": "bearer",
            "user": user
        }
    }


@router.post("/login")
def login(request: auth.LoginRequest):
    """
    Authenticate user credentials.
    Returns a generic 401 response for any invalid combination to protect against
    user enumeration attacks.
    """
    user = db_operations.get_user_by_email(request.email)

    if not user or not auth.verify_password(request.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Generate JWT token
    access_token = auth.create_access_token(
        data={
            "sub": str(user["id"]),
            "email": user["email"],
            "name": user["full_name"]
        }
    )

    # Sanitize user dict (remove password_hash)
    user_data = {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user.get("role", "user"),
        "plan": user.get("plan", "internal_demo"),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at")
    }

    return {
        "status": "success",
        "data": {
            "access_token": access_token,
            "token_type": "bearer",
            "user": user_data
        }
    }


@router.get("/me")
def get_me(current_user: dict = Depends(auth.get_current_user)):
    """
    Retrieve authenticated user profile.
    Protected by the get_current_user JWT dependency.
    """
    return {
        "status": "success",
        "data": current_user
    }


@router.get("/usage")
@router.get("/me/usage")
def get_user_usage(current_user: dict = Depends(auth.get_current_user)):
    """
    Retrieve authoritative quota usage metrics for the authenticated user.
    Uses the exact UTC calendar-month boundary and counting rules as quota enforcement.
    Strictly tenant-scoped via the verified JWT token (never user-supplied).
    """
    user_id = current_user["id"]
    metrics = usage_service.get_user_usage_metrics(user_id)
    plan_key = current_user.get("plan", plans.get_default_registration_plan())
    plan_cfg = plans.get_plan_config(plan_key)

    return {
        "status": "success",
        "data": {
            "user_id": user_id,
            "plan": plan_key,
            "plan_name": plan_cfg.get("name", plan_key),
            "platform_mode": plans.get_platform_mode(),
            "enforce_usage_limits": plans.is_quota_enforcement_enabled(),
            "metrics": metrics,
            "limits": {
                "max_projects": plan_cfg.get("max_projects", -1),
                "monthly_test_runs": plan_cfg.get("monthly_test_runs", -1),
                "monthly_test_cases": plan_cfg.get("monthly_test_cases", -1),
                "monthly_ai_operations": plan_cfg.get("monthly_ai_operations", -1),
            },
            "features": plan_cfg.get("features", []),
        }
    }



@router.post("/logout")
def logout():
    """
    Stateless JWT logout endpoint.
    Because authentication uses stateless signed JWTs, the client must discard
    the access token from storage. Server-side token invalidation is not performed
    unless a dedicated token blacklist or revocation list is maintained.
    """
    return {
        "status": "success",
        "message": (
            "Logged out successfully. In this stateless JWT setup, the client "
            "must discard its token. Server-side invalidation is not performed."
        )
    }
