"""Celery async tasks for the order domain."""

from celery import shared_task


@shared_task
def send_order_created_event(order_id: int) -> None:
    """Push an ORDER_CREATED notification to downstream consumers."""
    pass


@shared_task(name="order.retry_payment")
def retry_payment(order_id: int) -> None:
    pass
