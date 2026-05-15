# Go 项目发现规则

> 通用规则见 [`_common.md`](./_common.md)。本文件补充 Gin / Echo / gRPC / GORM / robfig/cron 项目的语言特定模式。

## 首要扫描文件

- 构建：`go.mod`、`go.sum`、`Makefile`
- 配置：`config/*.yml` / `*.toml` / `*.env`
- 入口：`cmd/*/main.go`、`internal/server/*.go`、`api/*.go`
- 模型：`internal/model/*.go`、`*.go` 中带 `TableName()` 方法的 struct
- 异步：使用 `kafka-go`、`sarama`、`nats.go`、`asynq` 的消费者

## 路由识别

| 框架 | 形态 | 角色 |
| --- | --- | --- |
| net/http | `http.HandleFunc("/...", handler)` | controller |
| Gin | `r.GET("/...", h.Handler)` / `router.Group("/...")` | controller |
| Echo | `e.GET("/...", h)` | controller |
| Chi / gorilla/mux | `r.Get("/...", h)` | controller |
| gRPC | `pb.RegisterXxxServer(s, impl)` | controller |

`router.Group("/api/v1")` 形式的前缀需要在 AI 富化时手动拼接到子路径前。

## 结构体角色推断

- `*Handler` / `*Controller` 后缀：controller
- `*Service` / `*Svc`：service
- `*Repository` / `*Repo`：repository
- 实现了 `TableName() string`：entity
- `*Client`：external-client
- `*Job`：scheduler
- 实现了 gRPC 服务端 stub（`UnimplementedXxxServer` 嵌入）：controller

## 数据库识别

- GORM：`func (T) TableName() string { return "..." }` 或 `db.Table("t_xxx")`
- sqlx / sql：通过 SQL 字符串中的表名识别（需要 AI 富化）
- ent：`ent.Schema` 实体定义

## 异步 / 调度信号

- robfig/cron：`cron.New()` + `cron.AddFunc("0 * * * *", fn)`
- Kafka：`sarama.NewConsumerGroup`、`kafka.NewReader`
- NATS：`nats.Connect`、`Subscribe(...)`
- asynq：`asynq.NewServer`、`mux.HandleFunc(taskType, ...)`

## Go 风险信号

- `db.Transaction(func(tx *gorm.DB) error {...})`
- `tx.Begin()` / `tx.Commit()` / `tx.Rollback()`
- `sync.Mutex` / `sync.RWMutex` / `sync.Once` / `atomic.*`
- `go func() {...}()` 启动 goroutine（注意 panic 是否被 recover）
- channel 阻塞与 select 超时
- `context.WithTimeout` / `context.WithCancel` 边界
- 外部 HTTP/RPC 调用嵌入 transaction 内

## 已知限制（regex 模式）

- 复杂泛型签名可能无法被正确解析
- 多文件接口与实现的对照只能由 AI 富化阶段补全
- `chi.Router` 多层 `Route(...)` 嵌套的前缀需要人工拼接

## 推荐 AI 富化补强

- 把 `Handler.Register(r)` 的路由表手抄成一段流程图
- 给 gRPC 接口对照 proto 文件，列出每个 method 的业务用途
- 把 context 上的关键 key（trace id、user id 等）汇总到 cross-cutting/observability.md
