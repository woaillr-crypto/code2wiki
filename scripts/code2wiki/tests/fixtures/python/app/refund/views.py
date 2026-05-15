"""Refund Class-Based Views (Django REST Framework).

These views are routed in urls.py via ``RefundListView.as_view()`` —
the class itself doesn't declare its path, but it must be recognised as
a controller because it IS the HTTP entry point.
"""

from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response


class RefundListView(generics.ListAPIView):
    """List all refunds for the current user."""
    serializer_class = None  # placeholder
    queryset = None

    def get_queryset(self):
        return []


class RefundDetailView(generics.RetrieveAPIView):
    """Fetch a single refund by id."""
    serializer_class = None
    queryset = None


class RefundApproveView(APIView):
    """Approve or reject a refund (admin-only)."""

    def post(self, request, pk):
        return Response({"id": pk, "status": "approved"})
