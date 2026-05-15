# 跨语言通用的发现规则

> 本文档列出所有语言插件共享的 BCL 发现策略。语言特定细节见同目录下的 `java.md` / `python.md` / `go.md` / `kotlin.md` / `typescript.md`。

## 优先扫描的文件类型

无论何种语言，先看以下文件：

- **构建/依赖清单**：`pom.xml` / `build.gradle*` / `go.mod` / `pyproject.toml` / `requirements.txt` / `package.json`
- **运行时配置**：`application*.yml` / `*.toml` / `*.env` / `*.json` / `*.properties`
- **项目自带文档**：`README*`、`docs/**`、`CHANGELOG*`、API 文档
- **入口路由**：HTTP / RPC / gRPC 注册的源文件
- **数据模型**：ORM 实体（JPA / SQLAlchemy / GORM / TypeORM / Prisma schema）+ 迁移 SQL
- **异步触发器**：MQ 消费者 / 调度任务 / Webhook 回调
- **测试**：与被改流程相关的单元/集成测试

## 域推断顺序（所有语言共享）

按以下顺序提取候选业务域：

1. URL 路径前缀（如 `/order`、`/refund`、`/user`）
2. 包/模块名（去掉公司前缀和技术分层段）
3. 构建模块名（Maven module / Gradle subproject / Go submodule / pnpm workspace）
4. 表名/实体名
5. Controller/Handler/Service 类名（去掉技术后缀）
6. MQ topic / 队列名 / 调度任务名

合并候选域只在「业务概念明显相同」时进行；同一技术分层不构成合并理由。

## 角色识别（语言无关的语义）

| 角色 | 业务含义 |
| --- | --- |
| `controller` | API/RPC 入口；接收请求并校验 |
| `service` | 业务流程编排 |
| `repository` | 数据访问层 |
| `entity` | 持久化模型（含表名） |
| `dto` | 传输对象 / 校验 schema |
| `mq-consumer` | 异步消息消费 / Celery / BullMQ |
| `scheduler` | 定时任务 / cron |
| `external-client` | 外部系统调用方 |
| `enum` | 状态枚举 / 业务码 |
| `config` | 配置 / DI 装配 |

具体如何识别这些角色，见对应语言的 discovery 文档。

## 通用风险信号

- 事务/原子操作边界
- 并发原语（锁、原子操作、协程/goroutine 启动点）
- 缓存读写
- 幂等键
- 状态码/状态枚举上的 if/switch
- 外部调用嵌在事务内
- 用户可见成功后才发生的异步副作用

## 推荐代码阅读顺序

1. 从 API/MQ/Job 触发点开始
2. Controller/Handler → Service → Repository/Mapper
3. DTO/Entity/状态枚举
4. 事务/幂等边界
5. 测试用例和历史需求示例
6. 用精确文件路径更新 BCL
