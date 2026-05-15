"""Order business service — orchestrates persistence, cache and async tasks."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.order.models import Order, OrderStatus
from app.order.tasks import send_order_created_event
from app.common.cache import cache


class OrderService:
    """Encapsulates order lifecycle: create, query, update status."""

    async def create(self, payload: dict) -> dict:
        async with transaction.atomic():
            order = Order(user_id=payload["user_id"], amount=payload["amount"],
                          status=OrderStatus.CREATED)
            await self._repo.save(order)
            send_order_created_event.delay(order.id)
            return {"id": order.id, "status": order.status.value}

    async def get(self, order_id: int) -> dict:
        cached = cache.get(f"order:{order_id}")
        if cached:
            return cached
        order = await self._repo.find_by_id(order_id)
        if not order:
            return {}
        result = {"id": order.id, "status": order.status.value}
        cache.set(f"order:{order_id}", result, ttl=60)
        return result

    async def update_status(self, order_id: int, status: str) -> dict:
        return {"id": order_id, "status": status}
