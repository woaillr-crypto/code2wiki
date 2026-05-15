package com.example.shop.cart;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;

@FeignClient(name = "PAYMENT-SERVICE", path = "/payment")
public interface PaymentClient {

    @PostMapping("/charge")
    String charge(String orderId);
}
