package com.example.order.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.example.order.entity.OrderEntity;
import com.example.order.repository.OrderRepository;
import javax.annotation.Resource;

/** 订单核心业务服务：负责创建订单、查询订单。 */
@Service
public class OrderService {

    @Resource
    private OrderRepository orderRepository;

    /** 创建订单 */
    @Transactional
    public String create(String payload) {
        OrderEntity entity = new OrderEntity();
        return orderRepository.save(entity);
    }

    public String get(Long id) {
        OrderEntity e = orderRepository.findById(id);
        return e == null ? "" : e.getStatus().name();
    }
}
