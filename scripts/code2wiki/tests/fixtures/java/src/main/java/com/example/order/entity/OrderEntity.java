package com.example.order.entity;

import com.baomidou.mybatisplus.annotation.TableName;

@TableName("t_order")
public class OrderEntity {

    private Long id;
    private String orderNo;
    private OrderStatus status;
    private Long userId;
    private Long amount;

    public OrderStatus getStatus() { return status; }
    public void setStatus(OrderStatus s) { this.status = s; }
}
