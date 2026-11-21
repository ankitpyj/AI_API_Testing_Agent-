from typing import Optional, Any, List
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

try:
    from agent_backend.auth import get_current_user
    from agent_backend import db_operations
    from agent_backend.usage_service import check_project_limit
    from agent_backend.engine.authentication.encryption import encrypt_secret, decrypt_secret
    from agent_backend.engine.authentication.project_auth import (
        validate_auth_header_name,
        build_auth_headers,
        mask_secret,
        sanitize_text,
    )
    from agent_backend.engine.parser.openapi_parser import load_openapi, extract_endpoints
except ImportError:
    from auth import get_current_user
    import db_operations
    from usage_service import check_project_limit
    from engine.authentication.encryption import encrypt_secret, decrypt_secret
    from engine.authentication.project_auth import (
        validate_auth_header_name,
        build_auth_headers,
        mask_secret,
    )
    from engine.parser.openapi_parser import load_openapi, extract_endpoints


router = APIRouter(prefix="/projects", tags=["Projects"])


def validate_http_url(url: str, field_name: str = "URL") -> str:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {field_name}. Must be an absolute HTTP or HTTPS URL (e.g. http://127.0.0.1:8000 or https://api.example.com)."
        )

    return cleaned


# ==========================================
# Request / Response Schemas
# ==========================================

class ProjectCreateRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    base_url: str = Field(..., min_length=7, max_length=255)
    openapi_url: Optional[str] = Field(None, max_length=255)
    auth_type: Optional[str] = Field("none", max_length=20)
    auth_header_name: Optional[str] = Field(None, max_length=100)
    auth_secret: Optional[str] = Field(None, max_length=1000)


class ProjectUpdateRequest(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    base_url: str = Field(..., min_length=7, max_length=255)
    openapi_url: Optional[str] = Field(None, max_length=255)
    auth_type: Optional[str] = Field(None, max_length=20)
    auth_header_name: Optional[str] = Field(None, max_length=100)
    auth_secret: Optional[str] = Field(None, max_length=1000)
    clear_secret: Optional[bool] = False


# ==========================================
# Project Endpoints
# ==========================================

@router.post("", status_code=status.HTTP_201_CREATED)
def create_project_endpoint(
    request: ProjectCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new project belonging to the authenticated user.
    Supports configuring target API authentication (none, bearer, api_key).
    Encrypts sensitive credentials with AES-256-GCM before saving to database.
    """
    check_project_limit(current_user["id"], user_plan=current_user.get("plan", "internal_demo"))

    base_url = validate_http_url(request.base_url, "Base URL")
    openapi_url = (
        validate_http_url(request.openapi_url, "OpenAPI URL")
        if request.openapi_url and request.openapi_url.strip()
        else None
    )

    auth_type = (request.auth_type or "none").strip().lower()
    if auth_type not in ("none", "bearer", "api_key"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid auth_type '{request.auth_type}'. Allowed values are 'none', 'bearer', and 'api_key'."
        )

    auth_header_name = None
    auth_secret_encrypted = None

    if auth_type == "bearer":
        if not request.auth_secret or not request.auth_secret.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="auth_secret is required when auth_type is 'bearer'."
            )
        auth_secret_encrypted = encrypt_secret(request.auth_secret.strip())

    elif auth_type == "api_key":
        if not request.auth_secret or not request.auth_secret.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="auth_secret is required when auth_type is 'api_key'."
            )
        try:
            auth_header_name = validate_auth_header_name(request.auth_header_name)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(e)
            )
        auth_secret_encrypted = encrypt_secret(request.auth_secret.strip())

    create_kwargs = {
        "user_id": current_user["id"],
        "project_name": request.project_name,
        "base_url": base_url,
        "openapi_url": openapi_url,
        "description": request.description,
    }
    if auth_type != "none" or auth_header_name or auth_secret_encrypted:
        create_kwargs["auth_type"] = auth_type
        create_kwargs["auth_header_name"] = auth_header_name
        create_kwargs["auth_secret_encrypted"] = auth_secret_encrypted

    project = db_operations.create_project(**create_kwargs)

    return {
        "status": "success",
        "data": project
    }


@router.get("")
def list_projects_endpoint(
    current_user: dict = Depends(get_current_user)
):
    """
    List all projects belonging to the authenticated user.
    Never exposes raw secrets or ciphertexts; exposes has_credentials boolean.
    """
    projects = db_operations.get_projects_by_user(user_id=current_user["id"])
    return {
        "status": "success",
        "data": projects
    }


@router.get("/{project_id}")
def get_project_endpoint(
    project_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Retrieve details of a specific project.
    Enforces user ownership: returns 404 if not found or belongs to another user.
    Never exposes raw secrets or ciphertexts; exposes has_credentials boolean.
    """
    project = db_operations.get_project_by_id(project_id, include_secret=False)
    if not project or project.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    return {
        "status": "success",
        "data": project
    }


@router.put("/{project_id}")
def update_project_endpoint(
    project_id: int,
    request: ProjectUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Update project details and authentication configuration.
    Enforces ownership: returns 404 if project doesn't exist or is not owned by user.
    Preserves existing encrypted credentials if not modified.
    """
    base_url = validate_http_url(request.base_url, "Base URL")
    openapi_url = (
        validate_http_url(request.openapi_url, "OpenAPI URL")
        if request.openapi_url and request.openapi_url.strip()
        else None
    )

    has_auth_change = (
        request.auth_type is not None
        or request.auth_header_name is not None
        or request.auth_secret is not None
        or request.clear_secret
    )

    update_kwargs = {
        "project_id": project_id,
        "user_id": current_user["id"],
        "project_name": request.project_name,
        "base_url": base_url,
        "openapi_url": openapi_url,
        "description": request.description,
    }

    if has_auth_change:
        existing = db_operations.get_project_by_id(project_id, include_secret=True)
        if not existing or existing.get("user_id") != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )

        auth_type = existing.get("auth_type", "none")
        if request.auth_type is not None:
            auth_type = request.auth_type.strip().lower()
            if auth_type not in ("none", "bearer", "api_key"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Invalid auth_type '{request.auth_type}'. Allowed values are 'none', 'bearer', and 'api_key'."
                )

        auth_header_name = existing.get("auth_header_name")
        auth_secret_encrypted = None
        clear_secret = bool(request.clear_secret) or (auth_type == "none")

        if auth_type == "none":
            auth_header_name = None
        elif auth_type == "bearer":
            auth_header_name = None
            if request.auth_secret and request.auth_secret.strip():
                auth_secret_encrypted = encrypt_secret(request.auth_secret.strip())
            elif not existing.get("has_credentials") and not existing.get("auth_secret_encrypted"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="auth_secret is required when configuring 'bearer' authentication."
                )
        elif auth_type == "api_key":
            header_candidate = request.auth_header_name if request.auth_header_name is not None else existing.get("auth_header_name")
            try:
                auth_header_name = validate_auth_header_name(header_candidate)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(e)
                )

            if request.auth_secret and request.auth_secret.strip():
                auth_secret_encrypted = encrypt_secret(request.auth_secret.strip())
            elif not existing.get("has_credentials") and not existing.get("auth_secret_encrypted"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="auth_secret is required when configuring 'api_key' authentication."
                )

        update_kwargs["auth_type"] = auth_type
        update_kwargs["auth_header_name"] = auth_header_name
        update_kwargs["auth_secret_encrypted"] = auth_secret_encrypted
        update_kwargs["clear_secret"] = clear_secret

    updated = db_operations.update_project(**update_kwargs)

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    return {
        "status": "success",
        "data": updated
    }


@router.delete("/{project_id}")
def delete_project_endpoint(
    project_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a project owned by the authenticated user.
    Returns 404 if not found or not owned.
    """
    success = db_operations.delete_project(
        project_id=project_id,
        user_id=current_user["id"]
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    return {
        "status": "success",
        "message": "Project deleted successfully"
    }


@router.get("/{project_id}/endpoints")
def get_project_endpoints_endpoint(
    project_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Discover and list all endpoints from the project's OpenAPI specification.
    Injects decrypted authentication credentials if the project is configured
    with Bearer or API Key authentication.
    """
    project = db_operations.get_project_by_id(project_id, include_secret=True)
    if not project or project.get("user_id") != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    openapi_url = project.get("openapi_url")
    if not openapi_url:
        openapi_url = project["base_url"].rstrip("/") + "/openapi.json"

    # Build auth headers if project has auth configured
    auth_headers = None
    secret = None
    if (
        project.get("auth_type")
        and project["auth_type"] != "none"
        and project.get("auth_secret_encrypted")
    ):
        try:
            secret = decrypt_secret(project["auth_secret_encrypted"])
            auth_headers = build_auth_headers(
                auth_type=project["auth_type"],
                auth_header_name=project.get("auth_header_name"),
                auth_secret=secret
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to decrypt project authentication secret: {sanitize_text(str(e))}"
            )

    try:
        openapi_data = load_openapi(openapi_url, auth_headers=auth_headers)
        raw_endpoints = extract_endpoints(openapi_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to load or parse OpenAPI specification from {openapi_url}: {sanitize_text(str(e), secret=secret)}"
        )

    endpoints_list = []
    for ep in raw_endpoints:
        endpoints_list.append({
            "path": ep.get("path"),
            "method": str(ep.get("method", "")).upper(),
            "summary": ep.get("summary") or ep.get("description") or "",
            "requires_body": bool(ep.get("request_body")),
            "responses": list(ep.get("responses", {}).keys()) if isinstance(ep.get("responses"), dict) else []
        })

    return {
        "status": "success",
        "data": {
            "project_id": project["id"],
            "project_name": project["project_name"],
            "base_url": project["base_url"],
            "openapi_url": openapi_url,
            "auth_type": project.get("auth_type", "none"),
            "auth_header_name": project.get("auth_header_name"),
            "has_credentials": bool(project.get("has_credentials")),
            "total_endpoints": len(endpoints_list),
            "endpoints": endpoints_list
        }
    }
