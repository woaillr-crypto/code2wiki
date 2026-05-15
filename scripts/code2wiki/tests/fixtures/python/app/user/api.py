"""User REST API."""

from fastapi import APIRouter
from app.user.service import UserService

router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/register")
async def register(payload: dict) -> dict:
    return await UserService().register(payload)


@router.get("/{user_id}")
async def get_user(user_id: int) -> dict:
    return await UserService().get(user_id)
