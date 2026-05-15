package com.example.shop.cart;

import org.springframework.web.bind.annotation.*;

/** Cart API: add/remove/checkout. */
@RestController
@RequestMapping("/api/cart")
public class CartController {

    @PostMapping("/add")
    public String add(@RequestBody String payload) {
        return "ok";
    }

    @PostMapping("/checkout")
    public String checkout(@RequestParam Long userId) {
        return "ok";
    }
}
