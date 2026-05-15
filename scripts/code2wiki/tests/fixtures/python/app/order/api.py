"""Order REST API — handles order creation and queries."""

from fastapi import APIRouter, Depends
from app.order.service import OrderService

router = APIRouter(prefix="/api/order", tags=["order"])


@router.post("/create")
async def create_order(payload: dict, svc: OrderService = Depends()) -> dict:
    return await svc.create(payload)


@router.get("/{order_id}")
async def get_order(order_id: int, svc: OrderService = Depends()) -> dict:
    return await svc.get(order_id)


@router.put("/{order_id}/status")
async def update_status(order_id: int, status: str, svc: OrderService = Depends()) -> dict:
    return await svc.update_status(order_id, status)
