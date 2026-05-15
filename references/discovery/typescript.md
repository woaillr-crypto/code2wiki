# TypeScript / JavaScript 项目发现规则

> 通用规则见 [`_common.md`](./_common.md)。本文件补充 NestJS / Express / TypeORM / Prisma / BullMQ 项目的语言特定模式。

## 首要扫描文件

- 构建：`package.json`、`tsconfig.json`、`pnpm-workspace.yaml`、`turbo.json`
- 配置：`*.env`、`config/*.ts`、Nest 的 `*.module.ts`
- 入口：`*.controller.ts`、Express `routes/*.ts`
- 模型：TypeORM 实体（`*.entity.ts`）、`prisma/schema.prisma`
- 异步：`*.processor.ts`（BullMQ）、`@nestjs/schedule` 装饰器
- 测试：`*.spec.ts`

## 路由识别

| 框架 | 形态 | 角色 |
| --- | --- | --- |
| NestJS | `@Controller("api/order")` + `@Get("/:id")` | controller |
| Express | `router.get("/...", handler)` | controller |
| Fastify | `fastify.get("/...", handler)` | controller |
| Hono | `app.get("/...", handler)` | controller |
| Koa | `router.get("/...", handler)` | controller |

NestJS 路径拼接逻辑：`@Controller("a")` + `@Get("b")` → `/a/b`。

## 类/装饰器角色推断

- `@Controller`：controller
- `@Injectable`：service
- `@Entity` + `@Column`：entity（TypeORM）
- `@Module`：config（依赖装配）
- `@Process("queue-name")`：mq-consumer（BullMQ）
- `@Cron("0 * * * *")`：scheduler（@nestjs/schedule）
- `@Guard` / `@UseGuards`：横切（权限）
- `*.dto.ts`、`*Schema.ts`、Zod schema：dto

## 数据库识别

- TypeORM：`@Entity(name)` 或 `@Entity({ name: "..." })`
- Prisma：`prisma/schema.prisma` 中的 `model X { ... @@map("...") }`（需要 AI 富化阶段单独读取）
- Sequelize：`sequelize.define("table", { ... })`
- Drizzle：`pgTable("table", { ... })`

## 异步 / 调度信号

- BullMQ：`new Queue("...")` + `new Worker(...)` + `@Process`
- Bull（旧版）：`queue.process(handler)`
- AWS SQS / RabbitMQ：消费者通常用 `@nestjs/microservices` 装饰
- `@Cron`、`@Interval`、`@Timeout`（`@nestjs/schedule`）
- Cloudflare / Vercel 边缘函数：另算

## 风险信号

- `manager.transaction(async (tx) => {...})`（TypeORM）
- `prisma.$transaction([...])` / `prisma.$transaction(async (tx) => {...})`
- `@Transaction`（typeorm-transactional）
- 并发：`Promise.all([...])` + 共享变量、未捕获的 reject
- 缓存：`cacheManager.set/get`、`@CacheKey`
- 长事务里嵌套 HTTP/gRPC 调用

## 已知限制（regex 模式）

- 跨多行的装饰器拆行（如 `@Get(\n  "/path"\n)`) 可能漏识别
- 复杂泛型 + 链式调用的方法签名提取不完整
- ~~`prisma/schema.prisma` 不在 `.ts` 后缀，需要 AI 富化阶段读取并补到 db_map.md~~ ✅ Phase 1.2 已修复：`parse_prisma_schema` 解析 `model X { ... @@map("table") }`，每个 `.prisma` 文件产生 1 个合成 FileInfo（role=entity），所有 model 进 db_map.md。15 条单测覆盖 `@@map` / 字段类型 / 可选 / 数组 / 注释 / 多 model / enum 排除。
- 动态路由（`useGlobalPrefix("api")` + `Reflect.defineMetadata`）不可见

## Phase 1 修复说明

- **Prisma schema**：fixture `tests/fixtures/typescript/prisma/schema.prisma` 包含 2 个 model（带 `@@map("t_user")` / `@@map("t_order")`）和 1 个 enum；scanner 输出含 `t_user` / `t_order` 表，model 名 `User` 用作 domain 推断回退（业务友好，不带 `t_` 表前缀污染）。
- **数组形装饰器路径**：仍待 Phase 4 拆 writer 时一并优化（NestJS `@Get(['/x', '/y'])` 现可识别但分类为单 mapping）。

## 推荐 AI 富化补强

- 把 NestJS 的 `@Module` 装配关系手抄成依赖图（哪些 service 注入到哪些 controller）
- 把 Prisma schema 翻译成 db_map.md（业务字段含义 + 索引 + 关系）
- 把 BullMQ 任务列表与 Redis 队列名对照
- 把 Guards / Interceptors 的全局/路由级生效范围写到 cross_cutting/auth.md
