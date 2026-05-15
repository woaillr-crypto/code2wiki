package com.example.shop.cart;

import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;

@RocketMQMessageListener(topic = "CART_TOPIC", consumerGroup = "CART_CG")
public class CartCheckoutConsumer implements RocketMQListener<String> {
    @Override
    public void onMessage(String body) {
        // handle checkout event
    }
}
