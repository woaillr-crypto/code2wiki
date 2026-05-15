package com.example.order.controller;

import org.springframework.web.bind.annotation.*;
import com.example.order.service.OrderService;
import javax.annotation.Resource;

/** 订单 API 入口，处理客户端下单与查询请求。 */
@RestController
@RequestMapping("/api/order")
public class OrderController {

    @Resource
    private OrderService orderService;

    @PostMapping("/create")
    public String create(@RequestBody String payload) {
        return orderService.create(payload);
    }

    @GetMapping("/{id}")
    public String get(@PathVariable Long id) {
        return orderService.get(id);
    }

    /** Aliased endpoints — Java array syntax for path list. */
    @GetMapping({"/list", "/all"})
    public String list() {
        return "ok";
    }
}
