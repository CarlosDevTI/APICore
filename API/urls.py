from django.urls import path
from .views import ListarFlujosPendientes, GenerarPDF

urlpatterns = [
    path('listar-flujos-pendientes/', ListarFlujosPendientes.as_view(), name='listar-flujos-pendientes'),
    path('generar-pdf/<int:cedula>/', GenerarPDF.as_view(), name='generar-pdf'),
]