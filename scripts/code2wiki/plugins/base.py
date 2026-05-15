"""Language scanner plugin contract.

Every language plugin returns a list of ``FileInfo`` records produced from the
project's source files. The orchestrator (``cli.main``) then runs the
language-agnostic domain inference, output writers, git analysis, and
cross-cutting registry emission over the combined list.

Standard ``FileInfo.extras`` keys are defined as constants in
:mod:`code2wiki.core.models` — always reference them via the constant
rather than the bare string so the source of truth stays single. As of
0.4.0 the supported keys are:

    EXTRAS_DUBBO_REFS    = "dubbo_refs"     list[str]  Java @DubboReference targets
    EXTRAS_FEIGN_DETAIL  = "feign_detail"   dict       Java @FeignClient parsed payload
    EXTRAS_MQ_ROLE       = "mq_role"        str        "producer" | "custom-consumer"
    EXTRAS_XXL_JOBS      = "xxl_jobs"       list[str]  Java XxlJob handler names
    EXTRAS_GRPC_SERVICES = "grpc_services"  list[str]  Go gRPC server stub names
    EXTRAS_KTOR_METHODS  = "ktor_methods"   list[str]  Kotlin Ktor HTTP verbs
    EXTRAS_CELERY_QUEUES = "celery_queues"  list[str]  Python Celery task names
    EXTRAS_PRISMA_MODELS = "prisma_models"  list[dict] TypeScript Prisma models

Add new keys to ``core.models`` first, document them here second.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class LanguageScanner(Protocol):
    """Contract every language plugin must satisfy."""

    name: str           # short id, e.g. "java", "python"
    display_name: str   # human label, e.g. "Java/Spring", "Python (Django/FastAPI)"

    def file_extensions(self) -> frozenset[str]:
        """Source file suffixes the plugin claims (e.g. {'.java'})."""

    def build_manifests(self) -> frozenset[str]:
        """Build/dep manifest filenames used by language detection."""

    def scan_project(self, root: Path, max_files: int) -> "ScanResult":
        """Walk the project, analyse files, return a ScanResult."""


class ScanResult:
    """Aggregated scan output handed to the core orchestrator."""

    def __init__(
        self,
        infos: list,
        ctx,
        aux_artifacts: list | None = None,
        domain_counter=None,
        grouped: dict | None = None,
    ) -> None:
        self.infos = infos
        self.ctx = ctx
        self.aux_artifacts = aux_artifacts or []
        self.domain_counter = domain_counter
        self.grouped = grouped or {}


class LanguagePluginBase:
    """Optional convenience base — plugins may inherit or duck-type Protocol."""

    name: str = ""
    display_name: str = ""

    def file_extensions(self) -> frozenset[str]:
        return frozenset()

    def build_manifests(self) -> frozenset[str]:
        return frozenset()

    def scan_project(self, root: Path, max_files: int) -> ScanResult:  # pragma: no cover - abstract
        raise NotImplementedError
