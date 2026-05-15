package com.example.order

object OrderRepository {

    fun findAll(): List<Order> = emptyList()

    fun findById(id: Long): Order? = null

    fun save(order: Order): Long = 0L

    fun updateStatus(id: Long, status: String) {}

    fun delete(id: Long) {}
}
