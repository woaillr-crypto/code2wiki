package com.example.order.mq;

import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;

@RocketMQMessageListener(topic = "ORDER_TOPIC", consumerGroup = "ORDER_CG")
public class OrderCreatedConsumer implements RocketMQListener<String> {

    @Override
    public void onMessage(String body) {
        // handle order created event
    }
}
