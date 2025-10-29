from django.urls import path
from .views import ListarFlujosPendientes, GenerarPDF, historial_pdfs

urlpatterns = [
    path('listar-flujos-pendientes/', ListarFlujosPendientes.as_view(), name='listar-flujos-pendientes'),
    path('generar-pdf/<str:cedula>/', GenerarPDF.as_view(), name='generar-pdf'),
    path('historial/', historial_pdfs, name='historial_pdfs'),
]