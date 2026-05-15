"""Unit tests for the FileInfo / JavaFileInfo dataclass and migration helpers.

Phase 2 promoted JavaFileInfo to a subclass of a language-agnostic FileInfo.
The schema covers three orthogonal concerns:

1. Direct construction with the **new** field names (``rpc_clients=``,
   ``extras=``) populates the dataclass cleanly.
2. Direct construction with **legacy** field names (``feign_clients=``,
   ``dubbo_refs=``, ``feign_detail=``, ``is_mq_producer=``,
   ``is_mq_consumer_custom=``, ``xxl_jobs=``) is routed through
   ``FileInfo.from_legacy_kwargs`` and stuffs the values into ``extras``.
3. Read-only ``@property`` bridges expose the legacy names so existing
   consumer code (analyze_java_project.py writers + indexes) keeps working.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest

from code2wiki.core.models import (
    EXTRAS_DUBBO_REFS,
    EXTRAS_FEIGN_DETAIL,
    EXTRAS_MQ_ROLE,
    EXTRAS_XXL_JOBS,
    FileInfo,
    JavaFileInfo,
    MQ_ROLE_CUSTOM_CONSUMER,
    MQ_ROLE_PRODUCER,
)


# ──────────────────────────────────────────────────────────────────────────────
# FileInfo direct construction (new schema)
# ──────────────────────────────────────────────────────────────────────────────

def test_fileinfo_minimal_construction():
    info = FileInfo(path="foo.py")
    assert info.path == "foo.py"
    assert info.language == "unknown"
    assert info.role == "support"
    assert info.domain == "unknown"
    assert info.rpc_clients == []
    assert info.extras == {}


def test_fileinfo_full_new_schema():
    info = FileInfo(
        path="src/order/api.py",
        language="python",
        package="src.order.api",
        class_name="OrderRouter",
        role="controller",
        domain="order",
        mappings=["/api/order"],
        rpc_clients=["payment-svc"],
        extras={"foo": "bar"},
    )
    assert info.rpc_clients == ["payment-svc"]
    assert info.extras == {"foo": "bar"}


def test_fileinfo_default_collections_are_independent():
    """Two instances must not share the same default list/dict."""
    a = FileInfo(path="a.py")
    b = FileInfo(path="b.py")
    a.rpc_clients.append("svc-a")
    a.extras["k"] = "v"
    assert b.rpc_clients == []
    assert b.extras == {}


# ──────────────────────────────────────────────────────────────────────────────
# Backward-compat @property bridges
# ──────────────────────────────────────────────────────────────────────────────

def test_feign_clients_property_reads_from_rpc_clients():
    info = FileInfo(path="x", rpc_clients=["a", "b"])
    assert info.feign_clients == ["a", "b"]


def test_dubbo_refs_property_reads_from_extras():
    info = FileInfo(path="x", extras={EXTRAS_DUBBO_REFS: ["DubA", "DubB"]})
    assert info.dubbo_refs == ["DubA", "DubB"]


def test_dubbo_refs_property_returns_empty_when_missing():
    info = FileInfo(path="x")
    assert info.dubbo_refs == []


def test_feign_detail_property_reads_from_extras():
    info = FileInfo(path="x", extras={EXTRAS_FEIGN_DETAIL: {"service": "SVC"}})
    assert info.feign_detail == {"service": "SVC"}


def test_feign_detail_returns_empty_dict_when_missing():
    info = FileInfo(path="x")
    assert info.feign_detail == {}


def test_is_mq_producer_property():
    info = FileInfo(path="x", extras={EXTRAS_MQ_ROLE: MQ_ROLE_PRODUCER})
    assert info.is_mq_producer is True
    assert info.is_mq_consumer_custom is False


def test_is_mq_consumer_custom_property():
    info = FileInfo(path="x", extras={EXTRAS_MQ_ROLE: MQ_ROLE_CUSTOM_CONSUMER})
    assert info.is_mq_consumer_custom is True
    assert info.is_mq_producer is False


def test_mq_role_unset_means_both_flags_false():
    info = FileInfo(path="x")
    assert info.is_mq_producer is False
    assert info.is_mq_consumer_custom is False


def test_xxl_jobs_property_reads_from_extras():
    info = FileInfo(path="x", extras={EXTRAS_XXL_JOBS: ["J1", "J2"]})
    assert info.xxl_jobs == ["J1", "J2"]


# ──────────────────────────────────────────────────────────────────────────────
# from_legacy_kwargs migration
# ──────────────────────────────────────────────────────────────────────────────

def test_from_legacy_maps_feign_clients_to_rpc_clients():
    info = FileInfo.from_legacy_kwargs(
        path="X.java", feign_clients=["SVC-A", "SVC-B"],
    )
    assert info.rpc_clients == ["SVC-A", "SVC-B"]


def test_from_legacy_prefers_explicit_rpc_clients_over_feign():
    info = FileInfo.from_legacy_kwargs(
        path="X.java",
        rpc_clients=["NEW"],
        feign_clients=["OLD"],
    )
    assert info.rpc_clients == ["NEW"]


def test_from_legacy_dubbo_refs_into_extras():
    info = FileInfo.from_legacy_kwargs(
        path="X.java", dubbo_refs=["A", "B"],
    )
    assert info.extras[EXTRAS_DUBBO_REFS] == ["A", "B"]


def test_from_legacy_feign_detail_into_extras():
    info = FileInfo.from_legacy_kwargs(
        path="X.java", feign_detail={"service": "FOO", "path": "/p"},
    )
    assert info.extras[EXTRAS_FEIGN_DETAIL] == {"service": "FOO", "path": "/p"}


def test_from_legacy_xxl_jobs_into_extras():
    info = FileInfo.from_legacy_kwargs(
        path="X.java", xxl_jobs=["job1"],
    )
    assert info.extras[EXTRAS_XXL_JOBS] == ["job1"]


def test_from_legacy_is_mq_producer_sets_mq_role():
    info = FileInfo.from_legacy_kwargs(
        path="X.java", is_mq_producer=True,
    )
    assert info.extras[EXTRAS_MQ_ROLE] == MQ_ROLE_PRODUCER
    assert info.is_mq_producer is True


def test_from_legacy_is_mq_consumer_custom_sets_mq_role():
    info = FileInfo.from_legacy_kwargs(
        path="X.java", is_mq_consumer_custom=True,
    )
    assert info.extras[EXTRAS_MQ_ROLE] == MQ_ROLE_CUSTOM_CONSUMER
    assert info.is_mq_consumer_custom is True


def test_from_legacy_both_flags_true_producer_wins_and_no_typeerror():
    """Regression: a single class can match BOTH detect_mq_producer AND
    detect_mq_custom (a class that sends events AND implements a custom RocketMQ
    handle is the canonical example). Prior to the fix, only the first
    flag was popped from kwargs and the second leaked through to the
    dataclass __init__ as an unrecognized keyword → TypeError.
    """
    info = FileInfo.from_legacy_kwargs(
        path="X.java",
        is_mq_producer=True,
        is_mq_consumer_custom=True,
    )
    # producer takes precedence
    assert info.extras[EXTRAS_MQ_ROLE] == MQ_ROLE_PRODUCER
    assert info.is_mq_producer is True
    assert info.is_mq_consumer_custom is False


def test_from_legacy_only_consumer_flag_works():
    """Regression: producer=False + consumer=True must pop both keys cleanly
    even though only one was True."""
    info = FileInfo.from_legacy_kwargs(
        path="X.java",
        is_mq_producer=False,
        is_mq_consumer_custom=True,
    )
    assert info.extras[EXTRAS_MQ_ROLE] == MQ_ROLE_CUSTOM_CONSUMER
    assert info.is_mq_consumer_custom is True


def test_from_legacy_both_flags_false_does_not_set_mq_role():
    info = FileInfo.from_legacy_kwargs(
        path="X.java",
        is_mq_producer=False,
        is_mq_consumer_custom=False,
    )
    assert EXTRAS_MQ_ROLE not in info.extras


def test_from_legacy_explicit_extras_preserved_alongside_legacy_fields():
    info = FileInfo.from_legacy_kwargs(
        path="X.java",
        extras={"custom_key": "value"},
        dubbo_refs=["DUB"],
    )
    assert info.extras["custom_key"] == "value"
    assert info.extras[EXTRAS_DUBBO_REFS] == ["DUB"]


def test_from_legacy_empty_legacy_lists_not_added_to_extras():
    """Empty legacy collections should NOT pollute extras with empty entries."""
    info = FileInfo.from_legacy_kwargs(
        path="X.java",
        dubbo_refs=[],
        feign_detail={},
        xxl_jobs=[],
    )
    assert EXTRAS_DUBBO_REFS not in info.extras
    assert EXTRAS_FEIGN_DETAIL not in info.extras
    assert EXTRAS_XXL_JOBS not in info.extras


def test_from_legacy_round_trip_via_properties():
    """A roundtrip through from_legacy_kwargs and the @property accessors
    yields the exact same field values."""
    info = FileInfo.from_legacy_kwargs(
        path="X.java",
        feign_clients=["S1"],
        dubbo_refs=["D1"],
        feign_detail={"service": "F1"},
        is_mq_producer=True,
        xxl_jobs=["J1"],
    )
    assert info.feign_clients == ["S1"]
    assert info.dubbo_refs == ["D1"]
    assert info.feign_detail == {"service": "F1"}
    assert info.is_mq_producer is True
    assert info.xxl_jobs == ["J1"]


# ──────────────────────────────────────────────────────────────────────────────
# JavaFileInfo subclass
# ──────────────────────────────────────────────────────────────────────────────

def test_javafileinfo_legacy_kwargs_constructor():
    """JavaFileInfo accepts the legacy kwarg names directly without users
    knowing about from_legacy_kwargs."""
    info = JavaFileInfo(
        path="X.java",
        package="com.x",
        class_name="X",
        annotations=["@RestController"],
        role="controller",
        domain="order",
        mappings=["/api/x"],
        tables=[],
        mq_listeners=[],
        scheduled=[],
        feign_clients=["SVC"],
        risk_signals=[],
        dubbo_refs=["DubX"],
        feign_detail={"service": "F"},
        is_mq_producer=True,
        xxl_jobs=["J1"],
    )
    # Legacy properties read correctly.
    assert info.feign_clients == ["SVC"]
    assert info.dubbo_refs == ["DubX"]
    assert info.feign_detail == {"service": "F"}
    assert info.is_mq_producer is True
    assert info.xxl_jobs == ["J1"]
    # New canonical fields hold the same data.
    assert info.rpc_clients == ["SVC"]
    assert info.extras[EXTRAS_DUBBO_REFS] == ["DubX"]
    # Default language for Java pipeline objects.
    assert info.language == "java"


def test_javafileinfo_new_schema_kwargs():
    """JavaFileInfo also accepts the new clean schema."""
    info = JavaFileInfo(
        path="X.java",
        package="com.x",
        class_name="X",
        role="controller",
        domain="order",
        rpc_clients=["SVC"],
        extras={EXTRAS_DUBBO_REFS: ["DubX"]},
    )
    assert info.rpc_clients == ["SVC"]
    assert info.dubbo_refs == ["DubX"]
    assert info.language == "java"


def test_javafileinfo_isinstance_of_fileinfo():
    info = JavaFileInfo(path="X.java")
    assert isinstance(info, FileInfo)


def test_javafileinfo_path_can_be_positional():
    """Regression: JavaFileInfo's custom __init__ must support positional path
    so callers can write JavaFileInfo("foo.java") just like the dataclass
    parent allows."""
    info = JavaFileInfo("foo.java")
    assert info.path == "foo.java"
    assert info.language == "java"


def test_javafileinfo_path_can_be_keyword():
    info = JavaFileInfo(path="bar.java")
    assert info.path == "bar.java"


# ──────────────────────────────────────────────────────────────────────────────
# Standard extras keys are stable string constants
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("constant,expected", [
    (EXTRAS_DUBBO_REFS, "dubbo_refs"),
    (EXTRAS_FEIGN_DETAIL, "feign_detail"),
    (EXTRAS_MQ_ROLE, "mq_role"),
    (EXTRAS_XXL_JOBS, "xxl_jobs"),
    (MQ_ROLE_PRODUCER, "producer"),
    (MQ_ROLE_CUSTOM_CONSUMER, "custom-consumer"),
])
def test_extras_keys_are_stable(constant, expected):
    """Pin the literal string values of these constants — third-party plugins
    or external readers may consume them as raw strings."""
    assert constant == expected
