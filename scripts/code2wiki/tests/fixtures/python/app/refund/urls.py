"""Django URL patterns for the refund domain."""

from django.urls import path
from . import views

urlpatterns = [
    path("refunds/", views.RefundListView.as_view(), name="refund-list"),
    path("refunds/<int:pk>/", views.RefundDetailView.as_view(), name="refund-detail"),
    path("refunds/<int:pk>/approve/", views.RefundApproveView.as_view(), name="refund-approve"),
]
