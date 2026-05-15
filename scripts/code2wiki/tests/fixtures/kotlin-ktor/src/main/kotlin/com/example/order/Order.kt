package com.example.order

data class Order(
    val id: Long? = null,
    val userId: Long,
    val amount: Long,
    val status: String,
)

data class CreateOrderRequest(
    val userId: Long,
    val amount: Long,
)
