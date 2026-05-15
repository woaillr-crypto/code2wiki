"""Unit tests for Python plugin pattern detection.

Phase 1.3 focus: Django Class-Based View recognition.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest

from code2wiki.plugins.language_python import (
    DJANGO_CBV_BASE_CLASSES,
    _extract_all_bases,
    _is_django_cbv,
)


# ──────────────────────────────────────────────────────────────────────────────
# _extract_all_bases
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_simple_base_class():
    src = "class Foo(Bar):\n    pass\n"
    assert _extract_all_bases(src) == {"Bar"}


def test_extract_multiple_classes():
    src = """
class A(BaseA):
    pass

class B(BaseB):
    pass
"""
    assert _extract_all_bases(src) == {"BaseA", "BaseB"}


def test_extract_multiple_bases_per_class():
    src = "class Foo(MixinA, MixinB, BaseC):\n    pass\n"
    assert _extract_all_bases(src) == {"MixinA", "MixinB", "BaseC"}


def test_extract_strips_module_qualifier():
    """`class V(rest.generics.ListAPIView):` must yield `ListAPIView`."""
    src = "class V(rest.generics.ListAPIView):\n    pass\n"
    assert _extract_all_bases(src) == {"ListAPIView"}


def test_extract_strips_generic_parameters():
    src = "class V(GenericMixin[Order]):\n    pass\n"
    assert _extract_all_bases(src) == {"GenericMixin"}


def test_extract_ignores_keyword_arguments():
    """metaclass=..., **kwargs forms are not base classes."""
    src = "class V(Base, metaclass=Meta):\n    pass\n"
    bases = _extract_all_bases(src)
    assert "Base" in bases
    assert "metaclass" not in bases
    assert "Meta" not in bases  # would need to inspect kwargs values; skip


def test_extract_handles_no_bases():
    src = "class Foo:\n    pass\n"
    assert _extract_all_bases(src) == set()


def test_extract_handles_empty_parens():
    src = "class Foo():\n    pass\n"
    assert _extract_all_bases(src) == set()


# ──────────────────────────────────────────────────────────────────────────────
# _is_django_cbv
# ──────────────────────────────────────────────────────────────────────────────

def test_listapiview_is_cbv():
    src = """
from rest_framework.generics import ListAPIView

class OrderListView(ListAPIView):
    pass
"""
    assert _is_django_cbv(src) is True


def test_apiview_is_cbv():
    src = """
from rest_framework.views import APIView

class OrderActionView(APIView):
    def post(self, request):
        pass
"""
    assert _is_django_cbv(src) is True


def test_modelviewset_is_cbv():
    src = """
from rest_framework.viewsets import ModelViewSet

class OrderViewSet(ModelViewSet):
    pass
"""
    assert _is_django_cbv(src) is True


def test_cbv_without_django_import_is_not_classified():
    """Guard against false positives: a class that happens to inherit from a
    user-defined ``ListView`` (or any name in the set) but where the file does
    NOT import django/rest_framework must NOT be misclassified."""
    src = """
class ListView:  # local helper, not a Django CBV
    pass

class MyHelper(ListView):
    pass
"""
    assert _is_django_cbv(src) is False


def test_django_listview_is_cbv():
    """Plain Django (not DRF) generic view should also be recognised."""
    src = """
from django.views.generic import ListView

class OrderListView(ListView):
    pass
"""
    assert _is_django_cbv(src) is True


def test_cbv_with_multiple_inheritance():
    """A CBV that also inherits a custom mixin must still be recognised."""
    src = """
from rest_framework.generics import ListAPIView

class MyView(LoggingMixin, AuthMixin, ListAPIView):
    pass
"""
    assert _is_django_cbv(src) is True


def test_cbv_with_qualified_module_path():
    src = """
import rest_framework

class OrderListView(rest_framework.generics.ListAPIView):
    pass
"""
    assert _is_django_cbv(src) is True


def test_plain_service_class_is_not_cbv():
    src = """
class OrderService:
    def create(self, payload):
        pass
"""
    assert _is_django_cbv(src) is False


def test_class_inheriting_from_user_mixin_only_is_not_cbv():
    src = """
class MyMixin:
    pass

class OrderService(MyMixin):
    pass
"""
    assert _is_django_cbv(src) is False


def test_class_inheriting_from_object_is_not_cbv():
    src = """
class Foo(object):
    pass
"""
    assert _is_django_cbv(src) is False


def test_empty_file_is_not_cbv():
    assert _is_django_cbv("") is False


# ──────────────────────────────────────────────────────────────────────────────
# DJANGO_CBV_BASE_CLASSES contains expected items
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cbv_set():
    return DJANGO_CBV_BASE_CLASSES


@pytest.mark.parametrize("base_name", [
    "ListAPIView", "RetrieveAPIView", "CreateAPIView", "DestroyAPIView",
    "ListCreateAPIView", "RetrieveUpdateDestroyAPIView",
    "APIView", "GenericAPIView",
    "ViewSet", "ModelViewSet", "ReadOnlyModelViewSet",
    "ListView", "DetailView", "CreateView", "UpdateView", "DeleteView",
    "FormView", "TemplateView",
])
def test_known_drf_django_bases_present(base_name, cbv_set):
    assert base_name in cbv_set
