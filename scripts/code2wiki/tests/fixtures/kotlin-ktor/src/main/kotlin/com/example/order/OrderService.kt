package com.example.order

import org.jetbrains.exposed.sql.transactions.transaction

object OrderService {

    fun list(): List<Order> = transaction {
        OrderRepository.findAll()
    }

    fun create(req: CreateOrderRequest): Long = transaction {
        OrderRepository.save(Order(userId = req.userId, amount = req.amount, status = "CREATED"))
    }

    fun get(orderId: Long): Order? = transaction {
        OrderRepository.findById(orderId)
    }

    fun updateStatus(orderId: Long) = transaction {
        OrderRepository.updateStatus(orderId, "PAID")
    }

    fun delete(orderId: Long) = transaction {
        OrderRepository.delete(orderId)
    }
}
