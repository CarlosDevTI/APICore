from django.urls import path
from .views import ListPendingFlowsView, GeneratePdfView

urlpatterns = [
    path('listar-flujos-pendientes/', ListPendingFlowsView.as_view(), name='listar-flujos-pendientes'),
    path('generar-pdf/<int:flujo_id>/', GeneratePdfView.as_view(), name='generar-pdf'),
]