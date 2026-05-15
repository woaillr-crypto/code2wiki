# Kotlin 项目发现规则

> 通用规则见 [`_common.md`](./_common.md)。Kotlin Spring 项目和 Java Spring 共享绝大部分识别逻辑——请同时参阅 [`java.md`](./java.md)。

## 首要扫描文件

- 构建：`build.gradle.kts`、`settings.gradle.kts`、`gradle.properties`
- 配置：与 Java 相同（`application*.yml` / `application*.properties` / bootstrap config）
- 模型：JPA 实体、MyBatis Mapper、Exposed Table 对象

## 路由识别

Kotlin Spring 项目所有 Spring 注解（`@RestController`、`@RequestMapping`、`@GetMapping` 等）一并识别，与 Java 一致。

Ktor 项目使用 routing DSL：

```kotlin
routing {
    route("/api/order") {
        get("/{id}") { ... }
        post("/create") { ... }
    }
}
```

当前 regex 不完全覆盖嵌套 DSL；Ktor 路由识别需要 AI 富化时手工补全。

## Kotlin 特有信号

- `data class` → 等价于 DTO
- `object` → 单例（多为 Service/Repository 的辅助）
- `sealed class` / `enum class` → 状态枚举
- `suspend fun` → 异步路径（视同 async/await）
- 扩展函数（top-level `fun T.foo(...)`）→ 多用于 util / converter

## 风险信号

- `@Transactional`（Spring 项目）
- `runBlocking { ... }` 把协程退回阻塞 — 注意线程切换
- `synchronized` 块、`Mutex().withLock`
- `Flow` 的并发收集（`buffer`、`flatMapMerge`）
- 协程 scope 泄漏（GlobalScope 启动）

## 已知限制

- ~~Ktor routing 多层嵌套 + lambda 形式的 path 提取不完整~~ ✅ Phase 1.1 已修复：`extract_ktor_routes` 状态机正确处理嵌套 `routing { route("/a") { route("/b") { get("/c") {...} } } }`，跳过字符串/注释/三引号 raw string 里的大括号，深度限制防御恶意嵌套
- 扩展函数所属域需要从文件路径推断，类名信号缺失
- Compose Multiplatform 项目（含 desktop/iOS 共享代码）会带入大量与后端无关文件

## Phase 1 修复说明

- **Ktor routing DSL**：23 条单测覆盖嵌套、字符串/注释跳过、深度安全。Spring Kotlin 项目仍走 Java 插件（避免回归）；纯 Ktor 项目（build.gradle.kts 含 `io.ktor` 且不含 `org.springframework`）走独立 Ktor pipeline。
- **数组形 path**：`@RequestMapping(path = ["/x", "/y"])` 和 `arrayOf("/a", "/b")` 都被识别为多条 mapping（fixture `tests/fixtures/java/` 含 `@GetMapping({"/list", "/all"})` 端到端验证）。

## 推荐 AI 富化补强

- 把 Ktor 路由 DSL 手抄成「路径 → handler 函数 → 业务用途」表
- 给 sealed class 的子类标注业务含义（状态机文档化）
- 协程作用域、线程切换的关键位置列入 risk_points.md
