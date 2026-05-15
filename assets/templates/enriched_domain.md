# <业务域中文名> (<domain-key>)

> 以下是 AI 富化后的域文档示例，展示 Phase 2 应产出的质量标准。

## 概述

（2-3 句话说清楚：这个域负责什么业务、谁在用、核心能力是什么）

例：花店商城域负责公司内部积分商城的商品浏览、下单、支付、发货全流程。
员工使用积分兑换实物商品，系统通过 Dubbo RPC 访问数据层，
下单和物流状态变更通过 RocketMQ 异步通知。

## 核心概念

| 概念 | 代码类 | 业务含义 |
|------|--------|----------|
| 订单 | FlowerShopOrder | 员工用积分兑换商品生成的购买记录 |
| 商品 | Merchandise | 积分商城中的可兑换实物商品 |
| 积分 | Currency | 员工积分余额，由公司定期发放，可兑换商品 |

## 状态流转

```
OrderStatusEnum:
CREATED(待支付) → PAID(已支付) → DELIVERED(已发货) → RECEIVED(已收货)
      ↓                                                    ↑
CANCELLED(已取消)                              7天自动确认收货
```

## 核心流程

### 下单流程

```
用户选择商品 → 扫码进入下单页
    ↓
前端调用 POST /flower/shop/createOrder
    ↓
FlowerShopController.createOrder(OrderCreateRequest)
    ↓
FlowerShopService.createOrder()
    ├── 校验库存（RPC: MerchandiseRpcService.checkStock）
    ├── 校验积分余额（RPC: CurrencyRpcService.getBalance）
    ├── 冻结积分（@Transactional）
    ├── 创建订单（RPC: FlowerShopOrderRpcService.create）
    └── 发送订单创建消息（MQ: CommonsProducer → FLOWER_SHOP_ORDER_CREATED）
        ↓
FlowerShopSaveOrderFlowHandler 消费消息
    └── 记录订单流水到 order_flow 表
```

### 自动收货

```
XxlJob 定时扫描 → 查询发货超过 7 天未确认的订单
    ↓
FlowerShopAutoReceiveGoodsHandler
    ├── 更新订单状态为 RECEIVED
    └── 发送系统通知给用户
```

## 关键业务规则

| 规则 | 说明 | 代码位置 |
|------|------|----------|
| 库存校验 | 下单前检查商品库存 >= 购买数量 | FlowerShopService:L120 |
| 积分冻结 | 先冻结积分，确认收货后正式扣减 | ClientCurrencyService:L85 |
| 自动收货 | 发货 7 天后未操作自动确认收货 | FlowerShopAutoReceiveGoodsHandler |
| 取消退积分 | 取消订单释放冻结积分 | FlowerShopCancelOrderHandle |

## MQ 消息

| Topic/Tag | 生产者 | 消费者 | 业务含义 |
|-----------|--------|--------|----------|
| FLOWER_SHOP_ORDER_CREATED | FlowerShopService | FlowerShopSaveOrderFlowHandler | 订单创建后记录流水 |
| FLOWER_SHOP_AUTO_RECEIVE | 定时任务 | FlowerShopAutoReceiveGoodsHandler | 自动确认收货 |
| FLOWER_SHOP_CANCEL | 用户取消 | FlowerShopCancelOrderHandle | 取消订单释放积分 |

## 上下游交互

### 上游系统

| 系统 | 交互方式 | 用途 |
|------|----------|------|
| 员工系统 | Dubbo RPC (EmployeeRpcService) | 查询员工信息、验证身份 |
| 积分系统 | Dubbo RPC (CurrencyRpcService) | 查询/冻结/扣减积分余额 |

### 下游系统

| 系统 | 交互方式 | 用途 |
|------|----------|------|
| 通知系统 | MQ (CommonsProducer) | 发送下单成功/发货/收货通知 |
| 后台管理 | API (BackEndCommonController) | 运营管理商品和订单 |

## 数据变更示例

```sql
-- 创建订单
INSERT INTO flower_shop_order (order_id, user_id, merchandise_id, amount, status, ...)
VALUES ('ORD20240101001', 12345, 678, 100, 'CREATED', ...);

-- 确认收货
UPDATE flower_shop_order SET status = 'RECEIVED', receive_time = NOW()
WHERE order_id = 'ORD20240101001' AND status = 'DELIVERED';
```

## 风险提示

| 风险类型 | 说明 | 防护措施 |
|----------|------|----------|
| 并发扣减 | 积分扣减需要防止超扣 | Redisson 分布式锁 (FlowerShopUtils) |
| 重复消费 | MQ 消息可能重复投递 | 订单号唯一索引 + 状态校验 |
| 事务边界 | 积分扣减和订单创建在同一事务 | @Transactional + 注意 RPC 调用位置 |

## API 清单

| 方法 | 路径 | 业务用途 |
|------|------|----------|
| POST | /flower/shop/createOrder | 创建订单 |
| POST | /flower/shop/cancelOrder | 取消订单 |
| POST | /flower/shop/payOrder | 支付订单 |
| POST | /flower/shop/receiveOrder | 确认收货 |
| GET | /flower/shop/getOrderDetail | 查看订单详情 |
| GET | /flower/shop/getOrderStatus | 查询订单状态 |

## 常见变更场景

| 需求类型 | 需要修改的文件 | 注意事项 |
|----------|---------------|----------|
| 新增商品属性 | Merchandise Entity + DTO + 前端 | 历史数据默认值处理 |
| 修改积分规则 | ClientCurrencyService | 注意冻结/扣减/退还逻辑一致性 |
| 新增订单状态 | OrderStatusEnum + 状态流转逻辑 | 所有 switch/if 分支都要覆盖 |
| 新增 MQ 消费 | 新 Handler + Factory 注册 + Tag 枚举 | 参考 FlowerShopAutoReceiveGoodsHandler |
