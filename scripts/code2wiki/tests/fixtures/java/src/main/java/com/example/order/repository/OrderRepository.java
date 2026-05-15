package com.example.order.repository;

import org.apache.ibatis.annotations.Mapper;
import com.example.order.entity.OrderEntity;

@Mapper
public interface OrderRepository {
    String save(OrderEntity entity);
    OrderEntity findById(Long id);
}
