import secrets
from typing import Any
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import Settings, get_settings

basic_scheme = HTTPBasic(auto_error=True)

async def require_admin(credentials: HTTPBasicCredentials = Depends(basic_scheme), settings: Settings = Depends(get_settings)) -> str:
    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def get_container(request: Request) -> Any:
    return request.app.state.container