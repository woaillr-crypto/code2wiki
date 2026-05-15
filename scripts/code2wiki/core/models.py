"""Core data models shared across language plugins.

``FileInfo`` is the language-agnostic record every plugin returns: path,
package/module, role, domain, mappings, tables, etc. Language-specific signals
(Java's @DubboReference targets, NestJS modules, Prisma models, …) live in
the ``extras`` dict under documented ``EXTRAS_*`` keys.

``JavaFileInfo`` is a thin subclass of ``FileInfo`` that adds read-only
``@property`` accessors mapping legacy field names (``feign_clients``,
``dubbo_refs``, ``is_mq_producer``, ``xxl_jobs``, …) onto the new schema.
The Java pipeline + every writer that reads those legacy names continues to
work unchanged via these properties.

Plugins (Python/Go/Kotlin/TS) construct ``FileInfo`` (or ``JavaFileInfo``
when they want the auto-defaulted ``language="java"``) directly with the new
field names and ``extras`` dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# Standard extras keys (string constants)
# ──────────────────────────────────────────────────────────────────────────────
# Plugins share these conventional keys so cross-plugin readers know what to
# look for. Add new keys here as new language signals are detected.

EXTRAS_DUBBO_REFS = "dubbo_refs"          # list[str] — Java @DubboReference targets
EXTRAS_FEIGN_DETAIL = "feign_detail"      # dict — Java @FeignClient parsed payload
EXTRAS_MQ_ROLE = "mq_role"                # str — "producer" | "custom-consumer"
EXTRAS_XXL_JOBS = "xxl_jobs"              # list[str] — Java XxlJob handler names
EXTRAS_GRPC_SERVICES = "grpc_services"    # list[str] — Go gRPC server stub names
EXTRAS_KTOR_METHODS = "ktor_methods"      # list[str] — Kotlin Ktor HTTP verbs (parallel to mappings)
EXTRAS_CELERY_QUEUES = "celery_queues"    # list[str] — Python Celery task names
EXTRAS_PRISMA_MODELS = "prisma_models"    # list[dict] — TypeScript Prisma model objects

# Reserve the following keys for future phases — uncomment when the producing
# plugin lands. Keeping them as comments avoids polluting the public surface
# with constants that have no readers today.
#   "grpc_methods"        list[str] — per-service gRPC method names
#   "nest_module"         str       — TypeScript NestJS @Module ownership
#   "http_methods"        list[str] — per-mapping HTTP method labels

# Canonical mq_role values
MQ_ROLE_PRODUCER = "producer"
MQ_ROLE_CUSTOM_CONSUMER = "custom-consumer"


# ──────────────────────────────────────────────────────────────────────────────
# FileInfo — language-agnostic core schema
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FileInfo:
    """A scanner record for one source file.

    Language-specific signals (Java's @DubboReference, NestJS modules,
    Prisma models, etc.) live in :attr:`extras`. Use the ``EXTRAS_*``
    constants above as keys so cross-plugin readers can find them.
    """

    # Identity
    path: str
    language: str = "unknown"       # "java" | "python" | "go" | "kotlin" | "typescript"
    package: str | None = None      # module path / package / namespace
    class_name: str | None = None

    # Classification
    annotations: list[str] = field(default_factory=list)
    role: str = "support"           # controller / service / repository / entity / mq-consumer / scheduler / dto / enum / config / external-client / cache / support
    domain: str = "unknown"

    # HTTP / data / async signals
    mappings: list[str] = field(default_factory=list)       # HTTP routes
    tables: list[str] = field(default_factory=list)         # ORM tables
    mq_listeners: list[str] = field(default_factory=list)   # MQ consumer topics
    scheduled: list[str] = field(default_factory=list)      # scheduler / cron entries
    rpc_clients: list[str] = field(default_factory=list)    # cross-service RPC client refs (renamed from feign_clients)

    # Risk + content
    risk_signals: list[str] = field(default_factory=list)
    fields: list[dict] = field(default_factory=list)
    enum_values: list[str] = field(default_factory=list)
    public_methods: list[dict] = field(default_factory=list)
    class_doc: str = ""
    implements_list: list[str] = field(default_factory=list)

    # Static analysis
    call_targets: list[dict] = field(default_factory=list)

    # Language-specific payload (see EXTRAS_* constants for known keys)
    extras: dict[str, Any] = field(default_factory=dict)

    # ──────────────────────────────────────────────────────────────
    # Backward-compat property accessors.
    # These satisfy legacy field-name access from ``core/writers.py`` and
    # the Java pipeline (``plugins/language_java.py``). They are READ-ONLY:
    # plugins must write to ``rpc_clients`` / ``extras`` directly.
    #
    # The accessors stay indefinitely as long as the writers read these
    # names. Removing them requires migrating every consumer site in
    # ``core/writers.py`` and ``plugins/language_java.py`` to read
    # ``rpc_clients`` / ``extras[EXTRAS_*]`` instead.
    # ──────────────────────────────────────────────────────────────

    @property
    def feign_clients(self) -> list[str]:
        return self.rpc_clients

    @property
    def dubbo_refs(self) -> list[str]:
        return self.extras.get(EXTRAS_DUBBO_REFS, [])

    @property
    def feign_detail(self) -> dict:
        return self.extras.get(EXTRAS_FEIGN_DETAIL, {})

    @property
    def is_mq_producer(self) -> bool:
        return self.extras.get(EXTRAS_MQ_ROLE) == MQ_ROLE_PRODUCER

    @property
    def is_mq_consumer_custom(self) -> bool:
        return self.extras.get(EXTRAS_MQ_ROLE) == MQ_ROLE_CUSTOM_CONSUMER

    @property
    def xxl_jobs(self) -> list[str]:
        return self.extras.get(EXTRAS_XXL_JOBS, [])

    # ──────────────────────────────────────────────────────────────
    # Migration helpers
    # ──────────────────────────────────────────────────────────────

    @classmethod
    def from_legacy_kwargs(cls, **kwargs: Any) -> "FileInfo":
        """Construct a FileInfo accepting either the new or legacy field names.

        This is the bridge used by analyze_java_project.py's analyze_java_file
        during the Phase 2 transition. The function:

        - Maps legacy ``feign_clients`` → ``rpc_clients``.
        - Stuffs legacy Java-specific kwargs (``dubbo_refs``, ``feign_detail``,
          ``is_mq_producer``, ``is_mq_consumer_custom``, ``xxl_jobs``) into
          ``extras`` using the standard keys.
        - Forwards every other kwarg unchanged.
        """
        extras: dict[str, Any] = dict(kwargs.pop("extras", {}) or {})

        if "feign_clients" in kwargs and "rpc_clients" not in kwargs:
            kwargs["rpc_clients"] = kwargs.pop("feign_clients")
        else:
            kwargs.pop("feign_clients", None)

        if (val := kwargs.pop("dubbo_refs", None)):
            extras[EXTRAS_DUBBO_REFS] = list(val)
        if (val := kwargs.pop("feign_detail", None)):
            extras[EXTRAS_FEIGN_DETAIL] = dict(val)
        if (val := kwargs.pop("xxl_jobs", None)):
            extras[EXTRAS_XXL_JOBS] = list(val)

        # Pop both MQ flags unconditionally — otherwise a `True` in the first
        # branch leaves the second flag in kwargs and the trailing
        # ``cls(**kwargs)`` blows up with a TypeError. Producer wins when both
        # are True (e.g. a class that sends events AND implements a custom
        # consumer handle — common in RocketMQ Boot integrations).
        mq_producer = bool(kwargs.pop("is_mq_producer", False))
        mq_consumer_custom = bool(kwargs.pop("is_mq_consumer_custom", False))
        if mq_producer:
            extras[EXTRAS_MQ_ROLE] = MQ_ROLE_PRODUCER
        elif mq_consumer_custom:
            extras[EXTRAS_MQ_ROLE] = MQ_ROLE_CUSTOM_CONSUMER

        kwargs["extras"] = extras
        return cls(**kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# JavaFileInfo — legacy alias retained for the Java scanner
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class JavaFileInfo(FileInfo):
    """Backward-compatible subclass of FileInfo for the legacy Java pipeline.

    The Java scanner (``analyze_java_project.py``) still constructs instances
    using the legacy field names (``feign_clients=``, ``dubbo_refs=``,
    ``is_mq_producer=``, etc.). Those kwargs are routed through
    :meth:`FileInfo.from_legacy_kwargs` automatically so call sites do not
    have to be rewritten en masse.

    The ``language`` field defaults to ``"java"`` for instances created via
    this subclass (the base FileInfo defaults to ``"unknown"``).

    Note: ``path`` can be passed either positionally — ``JavaFileInfo("X.java")``
    — or as a keyword. The custom ``__init__`` accepts both forms.
    """

    def __init__(self, path: str | None = None, /, **kwargs: Any) -> None:
        if path is not None:
            kwargs["path"] = path
        # Dispatch through the legacy bridge if any legacy kwarg is present;
        # otherwise use the standard dataclass __init__.
        legacy_keys = {
            "feign_clients", "dubbo_refs", "feign_detail",
            "is_mq_producer", "is_mq_consumer_custom", "xxl_jobs",
        }
        if any(k in kwargs for k in legacy_keys):
            instance = FileInfo.from_legacy_kwargs(**kwargs)
            self.__dict__.update(instance.__dict__)
        else:
            super().__init__(**kwargs)
        # Default language for Java pipeline objects that don't specify it.
        if self.language == "unknown":
            self.language = "java"


# ──────────────────────────────────────────────────────────────────────────────
# ProjectContext / AuxArtifact / GitContext — moved out of analyze_java_project
# to break the import cycle introduced when JavaFileInfo became a FileInfo
# subclass living in this module.
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ProjectContext:
    dependencies: list[dict] = field(default_factory=list)
    has_rocketmq: bool = False
    has_kafka: bool = False
    has_rabbitmq: bool = False
    has_xxljob: bool = False
    has_dubbo: bool = False
    has_redis: bool = False
    has_mybatis: bool = False
    has_jpa: bool = False
    has_eureka: bool = False
    has_nacos: bool = False
    mq_framework_name: str = ""
    rpc_framework_name: str = ""
    config_keys: list[str] = field(default_factory=list)


@dataclass
class MyBatisXmlInfo:
    """Java MyBatis Mapper XML descriptor.

    The shape is MyBatis-specific (``namespace`` / ``sql_ids``) because the
    Java writer code reads these field names directly. The
    :data:`AuxArtifact` alias below is reserved for future generalisation
    to Prisma schemas and similar non-source descriptors, but is not yet
    consumed anywhere.
    """
    path: str
    namespace: str
    sql_ids: list[str]
    tables: list[str]


@dataclass
class GitContext:
    is_git_repo: bool = False
    hot_files: list[dict] = field(default_factory=list)      # [{path, count}]
    recent_commits: list[str] = field(default_factory=list)
    contributors: list[dict] = field(default_factory=list)   # [{name, count}]
    domain_activity: dict = field(default_factory=dict)      # {domain: commit_count}
    commit_keywords: list[str] = field(default_factory=list)


# Reserved alias for future generalisation to non-Java ORM descriptors
# (Prisma schema, GORM TableName mapping, etc.). Not consumed today —
# remove if no other auxiliary artifact types materialise.
AuxArtifact = MyBatisXmlInfo
