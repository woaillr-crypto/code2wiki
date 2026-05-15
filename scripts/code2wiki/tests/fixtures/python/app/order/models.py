"""SQLAlchemy models for the order domain."""

from enum import Enum
from sqlalchemy import Column, BigInteger, String
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OrderStatus(str, Enum):
    CREATED = "created"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "t_order"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger)
    amount = Column(BigInteger)
    status = Column(String(32))
