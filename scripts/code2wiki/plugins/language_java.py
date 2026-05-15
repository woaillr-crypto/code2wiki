"""Java/Spring scanner plugin.

The plugin owns all Java-specific scanning logic: regex patterns, per-file
analysis, project-context detection (pom.xml / application.yml), MyBatis XML
parsing, the cross-cutting writer, and the legacy pipeline runner.

Shared utilities (file walking, markdown rendering, domain inference, git
analysis, output writers) live in ``code2wiki.core.*``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from code2wiki.core.domain import (
    CLASS_SUFFIXES,
    PATH_PREFIX_SEGMENTS,
    TECH_SEGMENTS,
    class_name_to_domain,
    infer_domain,
    merge_domains,
    normalize_domain,
    package_to_domain,
    path_to_domain,
    table_to_domain,
)
from code2wiki.core.git import (
    _git_cmd,
    analyze_git_history,
    generate_git_activity,
)
from code2wiki.core.io import (
    AI_ENRICHED_MARKER,
    ALWAYS_OVERWRITE,
    AUXILIARY_DIRS,
    AUXILIARY_SUFFIXES,
    CONFIG_SUFFIXES,
    IGNORE_DIRS,
    JAVA_SUFFIXES,
    SCANNER_MARKER,
    SQL_SUFFIXES,
    STRING_RE,
    extract_string_values,
    first_match,
    iter_auxiliary_files,
    iter_files,
    read_text,
    rel,
    write,
)
from code2wiki.core.markdown import (
    _extract_business_words,
    md_table,
    role_label,
    skill_name_from_project,
)
from code2wiki.core.models import (
    FileInfo,
    GitContext,
    JavaFileInfo,
    MyBatisXmlInfo,
    ProjectContext,
)
from code2wiki.core.writers import (
    build_keyword_domain_map,
    build_mermaid_domain_graph,
    extract_auxiliary_summary,
    generate_auxiliary_knowledge,
    generate_business_domain_map,
    generate_domain_docs,
    generate_playbooks,
    generate_root_skill,
)


class JavaPlugin:
    name = "java"
    display_name = "Java/Spring"

    def file_extensions(self) -> frozenset[str]:
        return frozenset({".java", ".kt", ".groovy"})

    def build_manifests(self) -> frozenset[str]:
        return frozenset({
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
        })

    def run_pipeline(self, args: argparse.Namespace) -> int:
        """Run the full Java analysis + generation pipeline.

        ``args`` must expose the same attributes the CLI accepts:
        project, output, max_files, top_domains, no_merge, force, no_git.

        We marshal ``args`` back into a string argv list and pass it
        explicitly to ``_run_legacy_pipeline``. No ``sys.argv`` mutation
        happens — this keeps library-mode (multi-threaded) callers safe.
        """
        new_argv = [str(args.project)]
        if args.output is not None:
            new_argv += ["--output", str(args.output)]
        if args.max_files is not None:
            new_argv += ["--max-files", str(args.max_files)]
        if args.top_domains is not None:
            new_argv += ["--top-domains", str(args.top_domains)]
        if args.no_merge:
            new_argv.append("--no-merge")
        if args.force:
            new_argv.append("--force")
        if args.no_git:
            new_argv.append("--no-git")

        # argparse can call sys.exit(2) on a malformed argv. Catch the
        # resulting SystemExit and return its code so the outer
        # orchestrator sees an int rather than a propagating exception.
        try:
            return _run_legacy_pipeline(new_argv)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1

    def fingerprint(self, root: Path) -> int:
        """Confidence score for auto-detection."""
        score = 0
        for manifest in self.build_manifests():
            if (root / manifest).exists():
                score += 10
        return score


PLUGIN = JavaPlugin()



def _java_language_label(ctx: ProjectContext) -> str:
    """User-visible label for the Java contribution in merged cross-cutting files."""
    parts: list[str] = ["Java"]
    sub: list[str] = []
    if ctx.has_rocketmq:
        sub.append(ctx.mq_framework_name or "RocketMQ")
    if ctx.has_kafka:
        sub.append("Kafka")
    if ctx.has_rabbitmq:
        sub.append("RabbitMQ")
    if ctx.has_dubbo:
        sub.append("Dubbo")
    if "Feign" in (ctx.rpc_framework_name or ""):
        sub.append("Feign")
    if sub:
        parts.append("(" + " / ".join(sub) + ")")
    return " ".join(parts)


def generate_cross_cutting(output: Path, java_infos: list[JavaFileInfo], ctx: ProjectContext) -> None:
    """Register all Java cross-cutting contributions with the orchestrator.

    Phase 4: this function no longer writes files directly. Each concern is
    pushed into the process-level registry via ``add_cross_cutting`` and the
    CLI runs ``emit_cross_cutting_files`` once all plugins finish.

    Single-plugin (java-only) projects still get byte-identical output
    because the orchestrator prepends ``# {title}\\n\\n`` exactly the way the
    legacy function did. Multi-plugin (mixed) projects get a merged file
    with ``## Java (Spring/RocketMQ)`` sections.

    The ``output`` argument is kept for backward compatibility — it is
    ignored, but callers (tests, legacy script) still pass it.
    """
    from code2wiki.core.cross_cutting import add_cross_cutting
    label = _java_language_label(ctx)

    # ── MQ ──
    mq_consumers = [f for f in java_infos if f.role == "mq-consumer" or f.is_mq_consumer_custom]
    mq_producers = [f for f in java_infos if f.is_mq_producer]

    mq_body = ""
    if ctx.has_rocketmq or ctx.has_kafka or ctx.has_rabbitmq or mq_consumers:
        mq_body += f"## 本项目的 MQ 实现方式\n\n"
        if ctx.has_rocketmq:
            mq_body += "本项目使用 **" + ctx.mq_framework_name + "** 作为消息中间件。\n\n"
            mq_body += "### 技术架构\n\n"
            mq_body += "- **Consumer 抽象**：自定义 `RocketMqHandle` 接口 + `RocketMqHandleFactory` 工厂路由\n"
            mq_body += "- **Producer**：`CommonsProducer`\n"
            mq_body += "- **Tag 管理**：`CommonsTagEnum` / `CommonsDelayMqTagEnums` 等枚举\n"
            mq_body += "- **消费者位置**：`mq/` 包和 `events/consumer/handler/` 包\n\n"
        elif ctx.has_kafka:
            mq_body += "本项目使用 **Kafka** 作为消息中间件。\n\n"
        elif ctx.has_rabbitmq:
            mq_body += "本项目使用 **RabbitMQ** 作为消息中间件。\n\n"

        if mq_consumers:
            mq_body += "## Consumer 清单\n\n"
            consumer_rows = [[f.domain, f.class_name or "-", f.class_doc or "-", f.path]
                           for f in sorted(mq_consumers, key=lambda x: (x.domain, x.path))]
            mq_body += md_table(["业务域", "Consumer 类", "说明", "文件"], consumer_rows, 100) + "\n\n"

        if mq_producers:
            mq_body += "## Producer 使用\n\n"
            producer_rows = [[f.domain, f.class_name or "-", f.path]
                           for f in sorted(mq_producers, key=lambda x: (x.domain, x.path))[:30]]
            mq_body += md_table(["业务域", "类", "文件"], producer_rows, 50) + "\n\n"

        mq_body += "## 开发注意事项\n\n"
        mq_body += "- 新增 Consumer 时需要实现 `RocketMqHandle` 接口并在 Factory 中注册 Tag 路由\n"
        mq_body += "- Tag 定义在 `CommonsTagEnum` 或相关枚举中\n"
        mq_body += "- 消费逻辑必须支持幂等（重复消费不能产生副作用）\n"
        mq_body += "- 避免在消费线程中执行不可控长事务\n"
        mq_body += "- 失败重试策略需要明确设计\n"
    else:
        mq_body += "未检测到 MQ 消息队列的使用。\n"

    add_cross_cutting(name="mq", title="MQ 消息队列", body=mq_body,
                       language="java", language_label=label)

    # ── Scheduler ──
    schedulers = [f for f in java_infos if f.role == "scheduler"]
    sched_body = ""
    if schedulers or ctx.has_xxljob:
        sched_body += "## 本项目的定时任务实现\n\n"
        if ctx.has_xxljob:
            sched_body += "本项目使用 **XxlJob** 作为分布式任务调度框架。\n\n"
        sched_body += "## 任务清单\n\n"
        sched_rows = []
        for f in schedulers:
            job_names = ", ".join(f.xxl_jobs) if f.xxl_jobs else ", ".join(f.scheduled) if f.scheduled else "-"
            sched_rows.append([f.domain, f.class_name or "-", job_names, f.class_doc or "-", f.path])
        sched_body += md_table(["业务域", "类", "任务名/Cron", "说明", "文件"], sched_rows, 50) + "\n\n"
        sched_body += "## 开发注意事项\n\n"
        sched_body += "- 任务必须支持重复执行（幂等）\n"
        sched_body += "- 注意执行频率和数据量对性能的影响\n"
        sched_body += "- 长时间运行的任务需要考虑超时和中断处理\n"
        if ctx.has_xxljob:
            sched_body += "- 新任务需要在 XxlJob Admin 控制台注册\n"
    else:
        sched_body += "未检测到定时任务。\n"
    add_cross_cutting(name="scheduler", title="定时任务", body=sched_body,
                       language="java", language_label=label)

    # ── Cache ──
    cache_files = [f for f in java_infos if "cache" in f.risk_signals or f.role == "cache"]
    cache_body = ""
    if cache_files or ctx.has_redis:
        cache_body += "## 本项目的缓存实现\n\n"
        if ctx.has_redis:
            cache_body += "本项目使用 **Redis** 作为缓存基础设施。\n\n"
        cache_classes = [f for f in java_infos if f.role == "cache"]
        if cache_classes:
            cache_body += "## 缓存类清单\n\n"
            cache_rows = [[f.domain, f.class_name or "-", f.class_doc or "-", f.path,
                          ", ".join(f.risk_signals) or "-"]
                         for f in sorted(cache_classes, key=lambda x: x.path)]
            cache_body += md_table(["业务域", "类", "说明", "文件", "风险信号"], cache_rows, 50) + "\n\n"
        if cache_files:
            cache_body += "## 使用缓存的文件\n\n"
            usage_rows = [[f.domain, f.class_name or "-", f.path]
                         for f in sorted(cache_files, key=lambda x: (x.domain, x.path))[:40]]
            cache_body += md_table(["业务域", "类", "文件"], usage_rows, 50) + "\n\n"
        cache_body += "## 开发注意事项\n\n"
        cache_body += "- 缓存更新和数据库写入的一致性\n"
        cache_body += "- 缓存穿透、击穿、雪崩的防护\n"
        cache_body += "- 缓存 key 的命名规范和过期时间\n"
        cache_body += "- 分布式锁场景下的缓存操作\n"
    else:
        cache_body += "未检测到明显的缓存使用。\n"
    add_cross_cutting(name="cache", title="缓存", body=cache_body,
                       language="java", language_label=label)

    # ── Transaction ──
    tx_files = [f for f in java_infos if "transaction" in f.risk_signals]
    tx_body = ""
    if tx_files:
        tx_body += f"## 概况\n\n检测到 {len(tx_files)} 个文件使用了 `@Transactional` 注解。\n\n"
        tx_body += "## 使用事务的文件\n\n"
        tx_rows = [[f.domain, f.class_name or "-", role_label(f.role), f.path]
                   for f in sorted(tx_files, key=lambda x: (x.domain, x.path))]
        tx_body += md_table(["业务域", "类", "角色", "文件"], tx_rows, 80) + "\n\n"
        tx_body += "## 开发注意事项\n\n"
        tx_body += "- 事务内不要包含外部调用（Dubbo/Feign/HTTP/MQ 发送）\n"
        tx_body += "- 注意事务传播级别（REQUIRED/REQUIRES_NEW）\n"
        tx_body += "- 大事务拆分，避免长时间持有数据库连接\n"
        tx_body += "- 检查 `@Transactional` 是否在 public 方法上（否则不生效）\n"
    else:
        tx_body += "未检测到 `@Transactional` 注解的使用。\n"
    add_cross_cutting(name="transaction", title="事务管理", body=tx_body,
                       language="java", language_label=label)

    # ── Concurrency/Lock ──
    lock_files = [f for f in java_infos if "concurrency-lock" in f.risk_signals]
    lock_body = ""
    if lock_files:
        lock_body += f"## 概况\n\n检测到 {len(lock_files)} 个文件使用了锁机制（Redisson/ReentrantLock/synchronized 等）。\n\n"
        lock_body += "## 使用锁的文件\n\n"
        lock_rows = [[f.domain, f.class_name or "-", f.path]
                    for f in sorted(lock_files, key=lambda x: (x.domain, x.path))]
        lock_body += md_table(["业务域", "类", "文件"], lock_rows, 80) + "\n\n"
        lock_body += "## 开发注意事项\n\n"
        lock_body += "- 分布式锁（Redisson）必须设置合理的过期时间\n"
        lock_body += "- 避免在持锁期间进行外部调用\n"
        lock_body += "- 注意死锁风险和锁竞争\n"
    else:
        lock_body += "未检测到显式锁的使用。\n"
    add_cross_cutting(name="concurrency", title="并发与锁", body=lock_body,
                       language="java", language_label=label)

    # ── Auth/Permission ──
    auth_files = [f for f in java_infos if "permission-auth" in f.risk_signals]
    auth_body = ""
    if auth_files:
        auth_body += f"## 概况\n\n检测到 {len(auth_files)} 个文件涉及权限/认证逻辑。\n\n"
        auth_body += "## 涉及权限的文件\n\n"
        auth_rows = [[f.domain, f.class_name or "-", role_label(f.role), f.path]
                    for f in sorted(auth_files, key=lambda x: (x.domain, x.path))]
        auth_body += md_table(["业务域", "类", "角色", "文件"], auth_rows, 80) + "\n\n"
    else:
        auth_body += "未检测到显式的权限/认证代码。可能使用了统一网关或拦截器。\n"
    add_cross_cutting(name="auth", title="认证与权限", body=auth_body,
                       language="java", language_label=label)
    # permission.md is a static pointer file — register it through the same path
    # so the orchestrator owns the disk write.
    add_cross_cutting(
        name="permission", title="权限控制",
        body="请参考 [auth.md](auth.md)，认证和权限在本项目中统一管理。\n",
        language="java", language_label=label,
    )

    # ── Idempotency ──
    idempotent_files = [f for f in java_infos if "idempotency" in f.risk_signals]
    idem_body = ""
    if idempotent_files:
        idem_body += f"## 概况\n\n检测到 {len(idempotent_files)} 个文件涉及幂等性处理。\n\n"
        idem_body += md_table(["业务域", "类", "文件"],
                              [[f.domain, f.class_name or "-", f.path]
                               for f in sorted(idempotent_files, key=lambda x: x.path)], 50) + "\n\n"
    else:
        idem_body += "未检测到显式的幂等性处理代码。但 MQ 消费和回调接口仍需确保幂等。\n"
    add_cross_cutting(name="idempotency", title="幂等性", body=idem_body,
                       language="java", language_label=label)

    # ── Dubbo RPC ──
    if ctx.has_dubbo:
        dubbo_files = [f for f in java_infos if f.dubbo_refs]
        dubbo_body = ""
        dubbo_body += f"## 概况\n\n本项目使用 **Apache Dubbo** 作为 RPC 框架，检测到 {len(dubbo_files)} 个文件引用了 `@DubboReference`。\n\n"
        all_dubbo_services = sorted({ref for f in java_infos for ref in f.dubbo_refs})
        if all_dubbo_services:
            dubbo_body += "## 引用的 RPC 服务\n\n"
            for svc in all_dubbo_services[:50]:
                dubbo_body += f"- `{svc}`\n"
            dubbo_body += "\n"
        dubbo_body += "## 按业务域分布\n\n"
        domain_dubbo: dict[str, set[str]] = defaultdict(set)
        for f in dubbo_files:
            for ref in f.dubbo_refs:
                domain_dubbo[f.domain].add(ref)
        dubbo_rows = [[domain, str(len(refs)), ", ".join(sorted(refs)[:5])]
                     for domain, refs in sorted(domain_dubbo.items(), key=lambda x: -len(x[1]))]
        dubbo_body += md_table(["业务域", "引用数", "示例服务"], dubbo_rows, 30) + "\n\n"
        dubbo_body += "## 开发注意事项\n\n"
        dubbo_body += "- RPC 调用有网络开销，避免在循环中频繁调用\n"
        dubbo_body += "- 注意超时设置和重试策略\n"
        dubbo_body += "- 不要在 `@Transactional` 事务内进行 RPC 调用\n"
        dubbo_body += "- RPC 接口变更需要协调上下游\n"
        add_cross_cutting(name="dubbo_rpc", title="Dubbo RPC", body=dubbo_body,
                           language="java", language_label=label)

    # ── Feign RPC ──
    feign_files = [f for f in java_infos if f.feign_detail and f.feign_detail.get("service")]
    if feign_files or "Feign" in ctx.rpc_framework_name:
        feign_body = ""
        feign_body += f"## 概况\n\n本项目使用 **{ctx.rpc_framework_name}** 进行服务间 HTTP RPC 调用"
        if ctx.has_eureka:
            feign_body += "，通过 **Eureka** 注册中心发现服务"
        elif ctx.has_nacos:
            feign_body += "，通过 **Nacos** 注册中心发现服务"
        feign_body += f"。\n\n检测到 {len(feign_files)} 个 `@FeignClient` 接口定义。\n\n"

        service_map: dict[str, list] = defaultdict(list)
        for f in feign_files:
            svc = f.feign_detail["service"]
            service_map[svc].append(f)

        feign_body += "## 调用的远程服务\n\n"
        svc_rows = []
        for svc, svc_files in sorted(service_map.items(), key=lambda x: -len(x[1])):
            clients = ", ".join(f.class_name or "-" for f in svc_files[:3])
            domains = ", ".join(sorted({f.domain for f in svc_files}))
            paths = ", ".join(f.feign_detail.get("path", "") for f in svc_files if f.feign_detail.get("path"))
            svc_rows.append([svc, paths or "-", clients, domains])
        feign_body += md_table(["远程服务名", "路径前缀", "Feign 接口", "使用域"], svc_rows, 50) + "\n\n"

        feign_body += "## Feign 接口清单\n\n"
        detail_rows = []
        for f in sorted(feign_files, key=lambda x: x.feign_detail.get("service", "")):
            fd = f.feign_detail
            methods_str = ", ".join(fd.get("methods", [])[:5])
            if len(fd.get("methods", [])) > 5:
                methods_str += f" ... (共{len(fd['methods'])}个)"
            detail_rows.append([
                f.class_name or "-",
                fd["service"],
                fd.get("path") or "-",
                methods_str or "-",
                f.domain,
                f.path,
            ])
        feign_body += md_table(["接口类", "服务名", "路径", "方法", "所属域", "文件"], detail_rows, 80) + "\n\n"

        feign_body += "## 开发注意事项\n\n"
        feign_body += "- Feign 调用走 HTTP，注意网络延迟和超时设置\n"
        feign_body += "- 不要在 `@Transactional` 事务内进行 Feign 调用\n"
        feign_body += "- 新增 Feign 接口需确保目标服务已在注册中心注册\n"
        feign_body += "- 注意 Hystrix/Sentinel 熔断降级配置\n"
        feign_body += "- Feign 接口变更需要协调服务提供方同步发布\n"
        if ctx.has_eureka:
            feign_body += "- 服务名（如 `ORDER-SERVICE`）是注册中心的注册名，确保大小写一致\n"
        add_cross_cutting(name="feign_rpc", title="Feign HTTP RPC", body=feign_body,
                           language="java", language_label=label)

    # ── Observability ──
    add_cross_cutting(
        name="observability", title="可观测性",
        body=("本文件记录项目的日志、监控和链路追踪实现。\n\n"
              "## 日志\n\n大部分类使用 `@Slf4j`（Lombok）进行日志记录。\n\n"
              "## 需要人工补充\n\n"
              "- 日志规范和格式\n"
              "- 监控告警配置\n"
              "- 链路追踪（TraceId）的传递方式\n"),
        language="java", language_label=label,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Generation: Other docs
# ──────────────────────────────────────────────────────────────────────────────

# Main
# ──────────────────────────────────────────────────────────────────────────────



HTTP_MAPPING_RE = re.compile(
    r"@(RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*(?:\(([^)]*)\))?",
    re.MULTILINE,
)
PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)")
ANNOTATION_RE = re.compile(r"@([A-Za-z_]\w*)")
TABLE_RE = re.compile(r"@Table(?:Name)?\s*\(\s*(?:value\s*=\s*)?\"([^\"]+)\"", re.MULTILINE)
ENTITY_RE = re.compile(r"@(Entity|TableName|Table)\b")
FEIGN_RE = re.compile(r"@FeignClient\s*\(([^)]*)\)", re.MULTILINE)
FEIGN_VALUE_RE = re.compile(r'(?:value|name)\s*=\s*"([^"]+)"')
FEIGN_PATH_RE = re.compile(r'path\s*=\s*"([^"]+)"')
FEIGN_URL_RE = re.compile(r'url\s*=\s*"([^"]+)"')

# Standard MQ annotations
MQ_RE = re.compile(r"@(KafkaListener|RabbitListener|RocketMQMessageListener|JmsListener)\s*\(([^)]*)\)", re.MULTILINE)

# Broader RocketMQ/ONS detection
ROCKETMQ_HANDLE_RE = re.compile(r"\bimplements\s+\w*(?:RocketMq|MQ|Mq)Handle\b", re.MULTILINE)
ONS_IMPORT_RE = re.compile(r"import\s+com\.aliyun\.openservices\.ons\.", re.MULTILINE)
DEFAULT_MQ_CONSUMER_RE = re.compile(r"\b(?:DefaultMQPushConsumer|DefaultMQPullConsumer|MessageListenerConcurrently|MessageListenerOrderly)\b")
MQ_PRODUCER_RE = re.compile(r"\b\w*Producer\b.*\.send\b|\bCommonsProducer\b", re.MULTILINE)
MQ_TAG_RE = re.compile(r"\b\w*(?:Tag|Topic)Enum[s]?\b\.(\w+)")

# XxlJob
XXL_JOB_RE = re.compile(r'@XxlJob\s*\(\s*"([^"]+)"', re.MULTILINE)
JOB_HANDLER_RE = re.compile(r"@JobHandler\s*\(\s*(?:value\s*=\s*)?\"([^\"]+)\"", re.MULTILINE)
SCHEDULED_RE = re.compile(r"@Scheduled\s*\(([^)]*)\)", re.MULTILINE)
EXTENDS_IJOBHANDLER_RE = re.compile(r"\bextends\s+IJobHandler\b")

# Dubbo RPC
DUBBO_REF_RE = re.compile(r"@DubboReference\b")
DUBBO_SERVICE_RE = re.compile(r"@DubboService\b")
DUBBO_REF_TYPE_RE = re.compile(r"@DubboReference[^;]*\n\s*private\s+(\w+)\s+(\w+)\s*;", re.MULTILINE)

# Entity/DTO field extraction — 避免 \s 匹配换行导致跨行回溯
FIELD_SIMPLE_RE = re.compile(r"private\s+([\w<>,? ]+?)\s+(\w+)\s*;")

# Enum values — 限制匹配范围，避免在大文件中 DOTALL 回溯
ENUM_BODY_RE = re.compile(r"\benum\s+\w+[^{]{0,200}\{([^}]{0,5000})\}")
ENUM_CONST_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*(?:\(|,|;|\{)", re.MULTILINE)

# Service public methods — 单行匹配，避免跨行回溯
PUBLIC_METHOD_RE = re.compile(
    r"public\s+([\w<>,? ]+?)\s+(\w+)\s*\(([^)]*)\)",
)

# Implements — 单行匹配
IMPLEMENTS_RE = re.compile(r"\bimplements\s+([\w<>, ]+?)(?:\s*\{)")

# Class javadoc — 简单匹配 /** 到 */ 块，后续由函数按行解析
JAVADOC_BLOCK_RE = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)

# 静态调用链：方法体中对 Service/Manager/RPC 的调用
SERVICE_CALL_RE = re.compile(
    r"\b(\w+(?:Service|Manager|Support|Repository|Mapper|Client|Producer|Sender|RpcService|Cache|Facade))"
    r"\s*\.\s*(\w+)\s*\(",
)
# 调用链过滤：跳过工具类方法
CALL_FILTER_METHODS = {
    "info", "warn", "error", "debug", "trace",  # 日志
    "equals", "hashCode", "toString", "getClass", "clone",  # Object
    "isEmpty", "isBlank", "isNotEmpty", "isNotBlank",  # StringUtils
    "of", "empty", "ofNullable", "get", "set", "put",  # 容器
    "format", "valueOf", "parse", "trim", "length", "size",
    "append", "add", "remove", "contains", "stream", "collect",
    "build", "builder", "newBuilder",
}
CALL_FILTER_CLASSES = {
    "Objects", "StringUtils", "CollectionUtils", "Collections", "Arrays",
    "Optional", "Stream", "Collectors", "Math", "System", "Thread",
    "String", "Integer", "Long", "Boolean", "BigDecimal", "UUID",
    "JSONObject", "JSON", "Gson", "ObjectMapper", "BeanUtils",
    "Assert", "Preconditions", "Lists", "Maps", "Sets",
    "Logger", "LoggerFactory",
}

TRANSACTIONAL_RE = re.compile(r"@Transactional\b")
LOCK_RE = re.compile(r"\b(ReentrantLock|synchronized|tryLock|Redisson|RLock|setIfAbsent|SETNX)\b")
CACHE_RE = re.compile(r"@(Cacheable|CacheEvict|CachePut)\b|\bRedisTemplate\b|\bStringRedisTemplate\b|\bRedissonClient\b")

# POM dependency parsing
POM_DEP_RE = re.compile(
    r"<dependency>\s*<groupId>\s*([\w.\-]+)\s*</groupId>\s*<artifactId>\s*([\w.\-]+)\s*</artifactId>",
    re.DOTALL,
)

# MyBatis XML
MYBATIS_NS_RE = re.compile(r'namespace\s*=\s*"([^"]+)"')
MYBATIS_SQL_RE = re.compile(r'<(select|insert|update|delete)\s+id\s*=\s*"([^"]+)"[^>]*>')
MYBATIS_TABLE_RE = re.compile(r'\b(?:from|into|update|join)\s+(\w+)', re.IGNORECASE)


#
# Consumer code that reads ``info.feign_clients`` / ``info.dubbo_refs`` /
# ``info.feign_detail`` / ``info.is_mq_producer`` / ``info.is_mq_consumer_custom``
# / ``info.xxl_jobs`` continues to work via @property bridges defined on
# FileInfo.

# ──────────────────────────────────────────────────────────────────────────────
# Java-specific extractors (used by analyze_java_file below)
# ──────────────────────────────────────────────────────────────────────────────

TECH_FIELD_NAMES = {
    "serialVersionUID", "log", "logger", "id", "createTime", "updateTime",
    "createdTime", "modifiedTime", "gmtCreate", "gmtModified", "gmtModify",
    "createBy", "updateBy", "creator", "updater", "modifier",
    "isDeleted", "deleted", "isDel", "version", "optimisticLock",
    "limit", "offset", "pageNum", "pageSize", "page", "size",
    "orderByClause", "distinct", "oredCriteria",
}
TECH_FIELD_TYPES = {
    "Logger", "Log", "Criteria", "GeneratedCriteria",
}


def extract_fields(text: str) -> list[dict]:
    """提取 private 字段声明（entity/DTO 等），过滤纯技术字段。"""
    fields = []
    for match in FIELD_SIMPLE_RE.finditer(text):
        ftype = match.group(1).strip()
        fname = match.group(2).strip()
        if fname in TECH_FIELD_NAMES or fname.startswith("$"):
            continue
        if ftype in TECH_FIELD_TYPES:
            continue
        # 过滤 Spring/框架注入字段
        if ftype.endswith(("Service", "Mapper", "Repository", "Client", "Producer",
                          "Sender", "Template", "Factory", "Config")):
            continue
        fields.append({"name": fname, "type": ftype})
    return fields[:40]


def extract_enum_values(text: str) -> list[str]:
    """提取枚举常量名。"""
    match = ENUM_BODY_RE.search(text)
    if not match:
        return []
    body = match.group(1)
    constants = ENUM_CONST_RE.findall(body)
    return constants[:30]


def extract_public_methods(text: str, role: str) -> list[dict]:
    """提取 public 方法签名（只对 Service/Manager/Handler 有意义）。"""
    if role not in ("service", "controller", "mq-consumer", "scheduler"):
        return []
    methods = []
    for match in PUBLIC_METHOD_RE.finditer(text):
        ret_type = match.group(1).strip()
        name = match.group(2).strip()
        params = match.group(3).strip()
        # 过滤 getter/setter/toString/equals
        if name.startswith(("get", "set", "is", "toString", "equals", "hashCode", "canEqual")):
            if len(name) < 20 and not params:
                continue
        methods.append({"name": name, "return_type": ret_type, "params": params[:200]})
    return methods[:30]


def extract_implements(text: str) -> list[str]:
    """提取 implements 的接口列表。"""
    match = IMPLEMENTS_RE.search(text)
    if not match:
        return []
    raw = match.group(1)
    return [s.strip() for s in re.split(r",\s*", raw) if s.strip()]


def extract_dubbo_refs(text: str) -> list[str]:
    """提取 @DubboReference 注入的服务类型名。"""
    refs = []
    for match in DUBBO_REF_TYPE_RE.finditer(text):
        refs.append(match.group(1))
    return refs


def extract_class_doc(text: str) -> str:
    """提取类级别的 javadoc 第一行。用简单字符串查找代替复杂正则。"""
    # 找到 class/interface/enum 声明的位置
    class_pos = -1
    for keyword in ("class ", "interface ", "enum ", "record "):
        pos = text.find(keyword)
        if pos != -1 and (class_pos == -1 or pos < class_pos):
            class_pos = pos
    if class_pos == -1:
        return ""
    # 向前搜索最近的 /** ... */ 块（限制范围避免误匹配）
    search_start = max(0, class_pos - 2000)
    chunk = text[search_start:class_pos]
    last_doc_start = chunk.rfind("/**")
    if last_doc_start == -1:
        return ""
    last_doc_end = chunk.find("*/", last_doc_start)
    if last_doc_end == -1:
        return ""
    raw = chunk[last_doc_start + 3:last_doc_end]
    lines = [line.strip().lstrip("*").strip() for line in raw.splitlines()]
    lines = [l for l in lines if l and not l.startswith("@")]
    return lines[0][:200] if lines else ""


def detect_mq_custom(text: str) -> bool:
    """检测自定义 RocketMQ Handle 模式。"""
    return bool(ROCKETMQ_HANDLE_RE.search(text) or ONS_IMPORT_RE.search(text) or DEFAULT_MQ_CONSUMER_RE.search(text))


def detect_mq_producer(text: str) -> bool:
    """检测 MQ 发送方。"""
    return bool(MQ_PRODUCER_RE.search(text))


def extract_xxl_jobs(text: str) -> list[str]:
    """提取 @XxlJob 注解的 job 名称。"""
    jobs = XXL_JOB_RE.findall(text)
    jobs.extend(JOB_HANDLER_RE.findall(text))
    if not jobs and EXTENDS_IJOBHANDLER_RE.search(text):
        jobs.append("<extends-IJobHandler>")
    return jobs


def extract_feign_detail(text: str) -> dict:
    """提取 @FeignClient 的结构化信息（服务名、path、url、接口方法列表）。"""
    match = FEIGN_RE.search(text)
    if not match:
        return {}
    args = match.group(1)
    service = ""
    # 先找 value/name，没有则找第一个字符串
    m = FEIGN_VALUE_RE.search(args)
    if m:
        service = m.group(1)
    else:
        strs = extract_string_values(args)
        if strs:
            service = strs[0]
    path = ""
    m = FEIGN_PATH_RE.search(args)
    if m:
        path = m.group(1)
    url = ""
    m = FEIGN_URL_RE.search(args)
    if m:
        url = m.group(1)
    # 提取接口方法列表
    methods: list[str] = []
    for mm in PUBLIC_METHOD_RE.finditer(text):
        name = mm.group(2).strip()
        if name not in ("equals", "hashCode", "toString"):
            methods.append(name)
    return {"service": service, "path": path, "url": url, "methods": methods[:20]}


def extract_call_targets(text: str, role: str) -> list[dict]:
    """从方法体中提取对 Service/Manager/RPC 等的调用。"""
    if role not in ("controller", "service", "mq-consumer", "scheduler"):
        return []
    targets: list[dict] = []
    seen: set[str] = set()
    for match in SERVICE_CALL_RE.finditer(text):
        cls = match.group(1)
        method = match.group(2)
        if cls in CALL_FILTER_CLASSES or method in CALL_FILTER_METHODS:
            continue
        key = f"{cls}.{method}"
        if key not in seen:
            seen.add(key)
            targets.append({"target_class": cls, "method": method})
    return targets[:50]




# ──────────────────────────────────────────────────────────────────────────────
# Project-level parsing (pom.xml, config, MyBatis XML)
# ──────────────────────────────────────────────────────────────────────────────

def parse_pom_dependencies(pom_paths: list[Path]) -> list[dict]:
    deps = []
    seen = set()
    for pom in pom_paths:
        text = read_text(pom, limit=500_000)
        for g, a in POM_DEP_RE.findall(text):
            key = f"{g}:{a}"
            if key not in seen:
                seen.add(key)
                deps.append({"groupId": g, "artifactId": a})
    return deps


def build_project_context(deps: list[dict], config_files: list[Path], root: Path) -> ProjectContext:
    ctx = ProjectContext(dependencies=deps)
    dep_arts = {d["artifactId"] for d in deps}
    dep_groups = {d["groupId"] for d in deps}

    # MQ framework detection
    if any("ons" in a or "rocketmq" in a for a in dep_arts) or any("rocketmq" in g for g in dep_groups):
        ctx.has_rocketmq = True
        ctx.mq_framework_name = "RocketMQ (阿里云 ONS)" if any("ons" in a for a in dep_arts) else "RocketMQ"
    if any("kafka" in a for a in dep_arts):
        ctx.has_kafka = True
        ctx.mq_framework_name = ctx.mq_framework_name or "Kafka"
    if any("rabbit" in a or "amqp" in a for a in dep_arts):
        ctx.has_rabbitmq = True
        ctx.mq_framework_name = ctx.mq_framework_name or "RabbitMQ"

    # Job framework
    if any("xxl-job" in a or "xxljob" in a for a in dep_arts):
        ctx.has_xxljob = True

    # RPC framework
    if any("dubbo" in a for a in dep_arts) or any("dubbo" in g for g in dep_groups):
        ctx.has_dubbo = True
        ctx.rpc_framework_name = "Dubbo"
    if any("openfeign" in a or "feign" in a for a in dep_arts):
        rpc_name = "Feign"
        # 检测注册中心
        if any("eureka" in a for a in dep_arts) or any("eureka" in g for g in dep_groups):
            ctx.has_eureka = True
            rpc_name = "Feign + Eureka"
        if any("nacos" in a for a in dep_arts):
            ctx.has_nacos = True
            rpc_name = "Feign + Nacos"
        if ctx.rpc_framework_name:
            ctx.rpc_framework_name += " / " + rpc_name
        else:
            ctx.rpc_framework_name = rpc_name

    # 从配置文件中补检 eureka/nacos（有些项目不直接在 pom 中声明）
    for cf in config_files[:20]:
        if cf.name.startswith("application") or cf.name.startswith("bootstrap"):
            if cf.suffix in {".yml", ".yaml", ".properties"}:
                text = read_text(cf, limit=50_000)
                if "eureka:" in text or "eureka." in text:
                    if not ctx.has_eureka:
                        ctx.has_eureka = True
                        if "Eureka" not in ctx.rpc_framework_name:
                            ctx.rpc_framework_name = (ctx.rpc_framework_name + " + Eureka").strip(" +/")
                if "nacos:" in text or "nacos." in text:
                    if not ctx.has_nacos:
                        ctx.has_nacos = True
                        if "Nacos" not in ctx.rpc_framework_name:
                            ctx.rpc_framework_name = (ctx.rpc_framework_name + " + Nacos").strip(" +/")

    # Data
    if any("mybatis" in a for a in dep_arts):
        ctx.has_mybatis = True
    if any("jpa" in a or "hibernate" in a for a in dep_arts):
        ctx.has_jpa = True
    if any("redis" in a or "redisson" in a or "lettuce" in a or "jedis" in a for a in dep_arts):
        ctx.has_redis = True

    # Parse config keys
    for cf in config_files[:20]:
        if cf.name.startswith("application") and cf.suffix in {".yml", ".yaml", ".properties"}:
            text = read_text(cf, limit=100_000)
            # Extract top-level config keys
            for line in text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and ":" in stripped:
                    key = stripped.split(":")[0].strip()
                    if key and not key.startswith("-"):
                        ctx.config_keys.append(key)

    return ctx


def parse_mybatis_xmls(all_files: list[Path], root: Path) -> list[MyBatisXmlInfo]:
    """解析 MyBatis XML mapper 文件。"""
    results = []
    for f in all_files:
        if f.suffix != ".xml":
            continue
        text = read_text(f, limit=200_000)
        if "mapper" not in text.lower()[:500] and "mybatis" not in text.lower()[:500]:
            continue
        ns = first_match(MYBATIS_NS_RE, text)
        if not ns:
            continue
        sql_ids = [f"{kind}.{sid}" for kind, sid in MYBATIS_SQL_RE.findall(text)]
        tables = sorted(set(t.lower() for t in MYBATIS_TABLE_RE.findall(text) if t.lower() not in {"set", "where", "and", "or", "values", "null"}))
        results.append(MyBatisXmlInfo(path=rel(f, root), namespace=ns, sql_ids=sql_ids, tables=tables))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Domain inference (same as v1 with minor fixes)
# ──────────────────────────────────────────────────────────────────────────────

def extract_mappings(text: str) -> list[str]:
    result = []
    for mapping, args in HTTP_MAPPING_RE.findall(text):
        values = extract_string_values(args)
        if values:
            result.extend(values)
        elif mapping == "RequestMapping":
            result.append("<class-level>")
    return list(dict.fromkeys(result))


def infer_role(path: Path, class_name: str | None, annotations: list[str], text: str) -> str:
    name = class_name or path.stem
    lower_path = path.as_posix().lower()
    ann = set(annotations)
    if {"RestController", "Controller"} & ann or "controller" in lower_path:
        return "controller"
    if "FeignClient" in ann or name.endswith(("Client", "Feign")):
        return "external-client"
    # 标准 MQ 注解
    if {"KafkaListener", "RabbitListener", "RocketMQMessageListener", "JmsListener"} & ann:
        return "mq-consumer"
    # 自定义 MQ Handle 模式（ONS/RocketMQ）
    if ROCKETMQ_HANDLE_RE.search(text) or (ONS_IMPORT_RE.search(text) and "/mq/" in lower_path):
        return "mq-consumer"
    if "/events/consumer/" in lower_path and ROCKETMQ_HANDLE_RE.search(text):
        return "mq-consumer"
    # XxlJob
    if XXL_JOB_RE.search(text) or "XxlJob" in ann or EXTENDS_IJOBHANDLER_RE.search(text):
        return "scheduler"
    if "Scheduled" in ann or "JobHandler" in ann or name.endswith(("Job", "Task", "Scheduler", "JobHandler")):
        return "scheduler"
    if ENTITY_RE.search(",".join(f"@{a}" for a in annotations)) or name.endswith(("Entity", "DO", "PO")):
        return "entity"
    if name.endswith(("Mapper", "Repository", "Dao")):
        return "repository"
    if name.endswith(("Service", "ServiceImpl", "Manager", "Facade", "Handler", "Processor", "DomainService")):
        return "service"
    if name.endswith(("DTO", "Request", "Response", "VO", "BO", "Command", "Dto")):
        return "dto"
    if name.endswith(("Enum", "Enums")) or ("/enums/" in lower_path and "enum " in text.lower()):
        return "enum"
    if "config" in lower_path or name.endswith("Config"):
        return "config"
    if name.endswith("Cache"):
        return "cache"
    return "other"




def risk_signals(text: str) -> list[str]:
    signals = []
    if TRANSACTIONAL_RE.search(text):
        signals.append("transaction")
    if LOCK_RE.search(text):
        signals.append("concurrency-lock")
    if CACHE_RE.search(text):
        signals.append("cache")
    if re.search(r"\b(idempotent|幂等|requestId|traceId|bizId|serialNo)\b", text, re.IGNORECASE):
        signals.append("idempotency")
    if re.search(r"\b(permission|auth|鉴权|权限|login|token)\b", text, re.IGNORECASE):
        signals.append("permission-auth")
    if re.search(r"\b(retry|重试|dead letter|DLQ|compensat|补偿)\b", text, re.IGNORECASE):
        signals.append("retry-compensation")
    return sorted(set(signals))


# ──────────────────────────────────────────────────────────────────────────────
# Java file analysis (enhanced)
# ──────────────────────────────────────────────────────────────────────────────

def analyze_java_file(path: Path, root: Path) -> JavaFileInfo:
    text = read_text(path)
    package = first_match(PACKAGE_RE, text)
    class_name = first_match(CLASS_RE, text)
    annotations = sorted(set(ANNOTATION_RE.findall(text)))
    mappings = extract_mappings(text)
    tables = sorted(set(TABLE_RE.findall(text)))
    mq = [",".join(extract_string_values(args)) or kind for kind, args in MQ_RE.findall(text)]
    scheduled = [args.strip() for args in SCHEDULED_RE.findall(text)]
    feign = [",".join(extract_string_values(args)) or args.strip() for args in FEIGN_RE.findall(text)]

    role = infer_role(path, class_name, annotations, text)
    domain = infer_domain(path, root, package, class_name, mappings, tables)

    # v2 新增提取
    fields = extract_fields(text) if role in ("entity", "dto", "enum", "other") else []
    enum_vals = extract_enum_values(text) if role == "enum" or (class_name and "Enum" in (class_name or "")) else []
    # 对所有看起来像 enum 的文件也尝试提取
    if not enum_vals and "enum " in text[:2000].lower():
        enum_vals = extract_enum_values(text)
    pub_methods = extract_public_methods(text, role)
    dubbo_refs = extract_dubbo_refs(text)
    is_mq_prod = detect_mq_producer(text)
    is_mq_cons = detect_mq_custom(text)
    xxl_jobs = extract_xxl_jobs(text)
    class_doc = extract_class_doc(text)
    impl_list = extract_implements(text)
    call_targets = extract_call_targets(text, role)
    feign_detail = extract_feign_detail(text) if role == "external-client" else {}

    # 如果检测到自定义 MQ consumer 但 role 不是 mq-consumer，纠正
    if is_mq_cons and role not in ("mq-consumer",):
        if "/mq/" in path.as_posix().lower() or "/events/consumer/" in path.as_posix().lower():
            role = "mq-consumer"

    if xxl_jobs and role != "scheduler":
        role = "scheduler"

    return JavaFileInfo(
        path=rel(path, root),
        package=package,
        class_name=class_name,
        annotations=annotations,
        role=role,
        domain=domain,
        mappings=mappings,
        tables=tables,
        mq_listeners=mq,
        scheduled=scheduled + xxl_jobs,
        feign_clients=feign,
        risk_signals=risk_signals(text),
        fields=fields,
        enum_values=enum_vals,
        public_methods=pub_methods,
        dubbo_refs=dubbo_refs,
        is_mq_producer=is_mq_prod,
        is_mq_consumer_custom=is_mq_cons,
        class_doc=class_doc,
        implements_list=impl_list,
        xxl_jobs=xxl_jobs,
        call_targets=call_targets,
        feign_detail=feign_detail,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Legacy pipeline entry point
# ──────────────────────────────────────────────────────────────────────────────
# ``_run_legacy_pipeline`` is what ``JavaPlugin.run_pipeline`` actually executes
# after marshalling its argparse Namespace back into ``sys.argv`` form. It is
# also re-exported as ``main`` by ``scripts/analyze_java_project.py`` for
# backwards compatibility with callers that still import the legacy script.


def _run_legacy_pipeline(argv: list[str] | None = None) -> int:
    """Run the Java analysis + generation pipeline.

    Args:
      argv: explicit argument vector to parse. When None, falls back to
        ``sys.argv[1:]``. Accepting an explicit list lets ``JavaPlugin.
        run_pipeline`` invoke us without mutating the global ``sys.argv``,
        which removes a latent library-mode hazard.
    """
    parser = argparse.ArgumentParser(description="Generate Business Context Layer for Java/Spring backend projects.")
    parser.add_argument("project", type=Path, help="Java project root")
    parser.add_argument("--output", type=Path, help="Output directory")
    parser.add_argument("--max-files", type=int, default=100_000)
    parser.add_argument("--top-domains", type=int, default=30)
    parser.add_argument("--no-merge", action="store_true", help="禁用域聚合")
    parser.add_argument("--force", action="store_true", help="强制覆盖 AI-ENRICHED 文件")
    parser.add_argument("--no-git", action="store_true", help="跳过 git history 分析")
    args = parser.parse_args(argv)

    from code2wiki.core.io import set_force_overwrite
    set_force_overwrite(args.force)

    project = args.project.resolve()
    if not project.exists() or not project.is_dir():
        raise SystemExit(f"Project path does not exist or is not a directory: {project}")

    output = (args.output.resolve() if args.output else project / ".code2wiki" / "business-context-layer")
    output.mkdir(parents=True, exist_ok=True)

    # Scan files
    all_files = list(iter_files(project, args.max_files))
    java_files = [p for p in all_files if p.suffix in JAVA_SUFFIXES]
    config_files = [p for p in all_files if p.suffix in CONFIG_SUFFIXES]
    sql_files = [p for p in all_files if p.suffix in SQL_SUFFIXES]
    build_files = [p for p in all_files if p.name in {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}]
    pom_files = [p for p in build_files if p.name == "pom.xml"]
    auxiliary_items = [extract_auxiliary_summary(path, project) for path in iter_auxiliary_files(project)]

    # Parse project context
    deps = parse_pom_dependencies(pom_files)
    ctx = build_project_context(deps, config_files, project)
    mybatis_xmls = parse_mybatis_xmls(all_files, project)

    print(f"[SCAN] Files: {len(all_files)}, Java: {len(java_files)}, Config: {len(config_files)}, POM deps: {len(deps)}")
    print(f"[SCAN] MQ: {ctx.mq_framework_name or 'none'}, RPC: {ctx.rpc_framework_name or 'none'}, "
          f"Redis: {ctx.has_redis}, XxlJob: {ctx.has_xxljob}, MyBatis XML: {len(mybatis_xmls)}")

    # Analyze Java files
    java_infos = [analyze_java_file(path, project) for path in java_files]
    domain_counter = Counter(info.domain for info in java_infos)
    role_counter = Counter(info.role for info in java_infos)

    # v3: 域聚合
    merge_map: dict[str, str] = {}
    if not args.no_merge:
        pre_merge_count = len([d for d in domain_counter if d != "unknown"])
        domain_counter, merge_map = merge_domains(java_infos, domain_counter)
        post_merge_count = len([d for d in domain_counter if d != "unknown"])
        if merge_map:
            print(f"[MERGE] 域聚合：{pre_merge_count} → {post_merge_count} 个域（合并了 {len(merge_map)} 个碎片域）")

    top_domains = [domain for domain, _ in domain_counter.most_common() if domain != "unknown"][:args.top_domains]

    # Generate domain groups first (needed for root skill)
    grouped: dict[str, list[JavaFileInfo]] = defaultdict(list)
    for info in java_infos:
        if info.domain in top_domains:
            grouped[info.domain].append(info)

    # Generate root skill (with keyword map and mermaid graph)
    generate_root_skill(output, project, top_domains, java_infos, grouped)

    # Generate inventory
    # 预计算统计数字（inventory 和 overview 都需要）
    mq_count = sum(1 for f in java_infos if f.role == "mq-consumer" or f.is_mq_consumer_custom)
    sched_count = sum(1 for f in java_infos if f.role == "scheduler")
    dubbo_count = sum(1 for f in java_infos if f.dubbo_refs)
    feign_count = sum(1 for f in java_infos if f.feign_detail and f.feign_detail.get("service"))

    inventory = {
        "project": str(project),
        "output": str(output),
        "language": "java",  # Phase 2: align with other plugins' inventory schema.
        "summary": {
            "total_files_scanned": len(all_files),
            "java_files": len(java_files),
            "config_files": len(config_files),
            "sql_files": len(sql_files),
            "build_files": len(build_files),
            "auxiliary_knowledge_files": len(auxiliary_items),
            "domain_count": len(domain_counter),
            "pom_dependencies": len(deps),
            "mybatis_xmls": len(mybatis_xmls),
        },
        "project_context": {
            "mq_framework": ctx.mq_framework_name,
            "rpc_framework": ctx.rpc_framework_name,
            "has_redis": ctx.has_redis,
            "has_xxljob": ctx.has_xxljob,
            "has_dubbo": ctx.has_dubbo,
            "has_eureka": ctx.has_eureka,
            "has_nacos": ctx.has_nacos,
            # Phase 2: renamed from "feign_clients" — generic across languages.
            "rpc_clients": feign_count,
        },
        "domains": domain_counter.most_common(),
        "roles": role_counter.most_common(),
        "build_files": [rel(p, project) for p in build_files],
    }
    write(output / "inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2))

    # Generate project overview
    tech_stack = []
    if ctx.has_rocketmq:
        tech_stack.append(ctx.mq_framework_name)
    if ctx.has_dubbo:
        tech_stack.append("Dubbo")
    if "Feign" in ctx.rpc_framework_name:
        label = "Feign"
        if ctx.has_eureka:
            label += " + Eureka"
        elif ctx.has_nacos:
            label += " + Nacos"
        tech_stack.append(label)
    if ctx.has_redis:
        tech_stack.append("Redis")
    if ctx.has_xxljob:
        tech_stack.append("XxlJob")
    if ctx.has_mybatis:
        tech_stack.append("MyBatis")
    if ctx.has_jpa:
        tech_stack.append("JPA")

    write(output / "00_project_overview.md", f"""# Project Overview

## 基本信息

- 项目路径：`{project}`
- Java/Kotlin 文件数：{len(java_files)}
- 配置文件数：{len(config_files)}
- 构建文件：{", ".join(rel(p, project) for p in build_files) or "未发现"}

## 技术栈

{", ".join(tech_stack) if tech_stack else "需要从 pom.xml 和代码中进一步确认"}

## 关键数字

| 维度 | 数量 |
| --- | --- |
| Controller (API 入口) | {role_counter.get("controller", 0)} |
| Service/Manager (业务服务) | {role_counter.get("service", 0)} |
| MQ Consumer (消息消费) | {mq_count} |
| Scheduler/Job (定时任务) | {sched_count} |
| Entity/DO (数据模型) | {role_counter.get("entity", 0)} |
| Enum (枚举/状态) | {role_counter.get("enum", 0)} |
| Repository/Mapper (数据访问) | {role_counter.get("repository", 0)} |
| 使用 Dubbo RPC 的文件 | {dubbo_count} |
| Feign 接口定义 | {feign_count} |
| Cache (缓存) | {role_counter.get("cache", 0)} |
| DTO/VO (传输对象) | {role_counter.get("dto", 0)} |

## 候选业务域

{md_table(["业务域候选", "代码文件数"], [[d, str(domain_counter[d])] for d in top_domains], args.top_domains)}

## 后续人工补强

- 将候选业务域改名为真实业务术语
- 为核心业务域补齐真实流程、状态流转和风险
- 将 `需要确认` 的内容交给熟悉业务的人验证
""")

    # Generate domain docs
    for domain, files in grouped.items():
        generate_domain_docs(output, domain, files, ctx, mybatis_xmls)

    # Generate indexes
    generate_business_domain_map(output, domain_counter, grouped)
    generate_auxiliary_knowledge(output, project, auxiliary_items)
    generate_cross_cutting(output, java_infos, ctx)
    generate_playbooks(output)

    # v4: Git history analysis
    git_ctx = GitContext()
    if not args.no_git:
        git_ctx = analyze_git_history(project, java_infos, top_domains)
        if git_ctx.is_git_repo:
            generate_git_activity(output, git_ctx, top_domains)
            print(f"[GIT] 热点文件: {len(git_ctx.hot_files)}, 贡献者: {len(git_ctx.contributors)}, "
                  f"commit 关键词: {', '.join(git_ctx.commit_keywords[:5]) or 'none'}")
        else:
            print("[GIT] 非 git 仓库，跳过 history 分析")

    # Global indexes
    api_rows = []
    db_rows = []
    code_rows = []
    dep_rows = []
    for info in java_infos:
        for mapping in info.mappings:
            api_rows.append([mapping, info.class_name or "-", info.domain, info.path])
        for table in info.tables:
            db_rows.append([table, info.class_name or "-", info.domain, info.path])
        code_rows.append([info.class_name or "-", role_label(info.role), info.domain, info.path])
        for client in info.feign_clients:
            dep_rows.append([client, info.class_name or "-", info.domain, info.path])

    write(output / "05_indexes" / "api_index.md", "# API Index\n\n" + md_table(["路径", "Controller", "业务域", "文件"], api_rows, 1000))
    write(output / "05_indexes" / "database_index.md", "# Database Index\n\n" + md_table(["表", "类", "业务域", "文件"], db_rows, 1000))
    write(output / "05_indexes" / "code_entrypoint_index.md", "# Code Entrypoint Index\n\n" + md_table(["类", "角色", "业务域", "文件"], code_rows, 2000))
    write(output / "05_indexes" / "dependency_index.md", "# Dependency Index\n\n" + md_table(["依赖", "调用类", "业务域", "文件"], dep_rows, 1000))

    write(output / "04_glossary" / "business_terms.md", "# 业务术语表\n\n请补充：业务术语 -> 所属业务域 -> 代码入口。\n")
    write(output / "04_glossary" / "status_codes.md", "# 状态码\n\n请补充：状态码/枚举 -> 含义 -> 流转约束 -> 来源文件。\n")
    write(output / "04_glossary" / "error_codes.md", "# 错误码\n\n请补充：错误码 -> 用户含义 -> 触发条件 -> 来源文件。\n")

    # v3: 域聚合日志
    if merge_map:
        merge_rows = [[old, new] for old, new in sorted(merge_map.items())]
        write(output / "domain_merge_log.md",
              "# 域聚合日志\n\n以下碎片域已被合并到父域：\n\n"
              + md_table(["原始域", "合并到"], merge_rows))

    # v3: 全局调用图
    call_graph_rows: list[list[str]] = []
    for info in java_infos:
        if info.call_targets and info.domain != "unknown":
            for ct in info.call_targets:
                call_graph_rows.append([
                    info.domain, info.class_name or "-",
                    ct["target_class"], ct["method"],
                ])
    if call_graph_rows:
        mermaid = build_mermaid_domain_graph(java_infos, top_domains)
        mermaid_section = f"\n## 域间依赖可视化\n\n{mermaid}\n" if mermaid else ""
        write(output / "05_indexes" / "call_graph.md",
              "# 全局调用图\n\n"
              "从 Controller/Service/MQ Consumer/Scheduler 中提取的静态调用关系。\n"
              + mermaid_section + "\n## 调用明细\n\n"
              + md_table(["调用方域", "调用方类", "被调用类", "方法"], call_graph_rows, 500))

    # Generation report
    write(output / "generation_report.md", f"""# Generation Report

## 生成结果

- 输出目录：`{output}`
- 已生成候选业务域：{len(grouped)}
- MQ Consumer 检测：{mq_count} 个（框架：{ctx.mq_framework_name or '未检测到'}）
- 定时任务检测：{sched_count} 个（XxlJob：{ctx.has_xxljob}）
- Dubbo RPC 引用：{dubbo_count} 个文件
- MyBatis XML：{len(mybatis_xmls)} 个
- 辅助知识文件：{len(auxiliary_items)} 个

## v3 增强

- **域聚合**：碎片域按前缀合并（合并了 {len(merge_map)} 个碎片域）
- **增量保护**：AI-ENRICHED 标记的文件不会被覆盖（使用 --force 强制覆盖）
- **静态调用链**：每个域生成 call_chains.md + 全局 call_graph.md
- **Git 历史分析**：热点文件 {len(git_ctx.hot_files)} 个, 贡献者 {len(git_ctx.contributors)} 个, commit 关键词 {len(git_ctx.commit_keywords)} 个
- 域 skill.md 包含 API/表/MQ/Job/Dubbo/风险的实质汇总
- concepts.md 填入了 Entity 字段和枚举值
- workflows.md 包含 Service 方法签名作为流程线索
- cross-cutting 文件包含叙述结构和开发注意事项
""")

    domain_file_count = sum(1 for _ in output.rglob("*.md")) + sum(1 for _ in output.rglob("*.json"))
    print(f"[OK] Business Context Layer generated at: {output}")
    print(f"[OK] Java: {len(java_files)}, Domains: {len(grouped)}, Output files: {domain_file_count}")
    return 0


