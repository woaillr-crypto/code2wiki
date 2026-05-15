"""User business service."""


class UserService:
    """User lifecycle: register, query, deactivate."""

    async def register(self, payload: dict) -> dict:
        return {"id": 1, "email": payload.get("email")}

    async def get(self, user_id: int) -> dict:
        return {"id": user_id}
