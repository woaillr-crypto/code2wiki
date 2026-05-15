# Java/Spring Discovery Heuristics

> 通用规则见 [`_common.md`](./_common.md)。本文件补充 Java/Spring/MyBatis/Dubbo/Feign 项目的语言特定模式。Kotlin Spring 项目也参考本文。

## Files To Inspect First

- Build: `pom.xml`, `build.gradle`, `settings.gradle`, `gradle.properties`.
- Runtime config: `application*.yml`, `application*.yaml`, `application*.properties`, bootstrap config.
- Project-owned docs: `README*`, `docs/**`, API docs, domain docs committed as ordinary project documentation.
- Inbound API: classes annotated with `@RestController`, `@Controller`, `@RequestMapping`, `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`.
- Business logic: `*Service`, `*ServiceImpl`, `*Manager`, `*Handler`, `*Processor`, `*Facade`, `*DomainService`.
- Persistence: `*Mapper`, `*Repository`, MyBatis XML, JPA entities, migration SQL.
- Async: `@KafkaListener`, `@RabbitListener`, RocketMQ listeners, `@Scheduled`, `@Async`, task/job packages.
- Integrations: `*Client`, `*Feign`, `@FeignClient`, `RestTemplate`, `WebClient`, SDK wrappers.
- Tests: unit/integration tests near changed flows.

Treat `.claude/skills`, `.cursor`, `.agents`, local memory folders, and personal prompt artifacts as optional auxiliary knowledge. Summarize them separately when present, but keep code/config/docs as the source of truth.

## Domain Inference

Infer candidate business domains from these signals, in order:

1. URL path prefixes such as `/order`, `/refund`, `/user`.
2. Package segments after company/product prefixes.
3. Module names in Maven/Gradle.
4. Table/entity names.
5. Controller/Service class names.
6. MQ topic or scheduler names.

Merge domains only when business concepts are clearly shared. Do not merge merely because code lives in the same technical module.

## Java/Spring Risk Signals

- Methods annotated with `@Transactional`.
- Distributed locks, `synchronized`, `ReentrantLock`, Redis locks.
- Idempotency keys, unique indexes, callback handlers, retry consumers.
- Cache annotations and direct Redis use.
- Status enum changes and switch/if branching over status.
- Large methods or services used by many controllers.
- External calls inside transactions.
- Async writes after user-visible success.

## Recommended Code Reading Pattern

1. Start from API or MQ/job trigger.
2. Follow Controller -> Service -> Manager -> Repository/Mapper.
3. Read DTO/entity/status enums.
4. Inspect transaction and idempotency boundaries.
5. Read tests and historical examples.
6. Update BCL docs with exact findings.
