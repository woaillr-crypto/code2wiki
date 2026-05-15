package com.example.order

import io.ktor.server.application.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*

fun Application.orderRoutes() {
    routing {
        route("/api/order") {
            get("/list") {
                call.respond(OrderService.list())
            }
            post("/create") {
                val req = call.receive<CreateOrderRequest>()
                OrderService.create(req)
                call.respondText("ok")
            }
            route("/{orderId}") {
                get("") {
                    val id = call.parameters["orderId"]!!.toLong()
                    call.respond(OrderService.get(id))
                }
                put("/status") {
                    val body = """
                        { "ignored": "this {} is inside a raw string" }
                    """
                    OrderService.updateStatus(call.parameters["orderId"]!!.toLong())
                }
                delete("") {
                    OrderService.delete(call.parameters["orderId"]!!.toLong())
                }
            }
        }
    }
}
