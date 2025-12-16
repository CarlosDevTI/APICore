from django.urls import path
from .views import ListarFlujosPendientes, GenerarPDF, historial_pdfs

urlpatterns = [
    path('comercial/listar-flujos-pendientes/', ListarFlujosPendientes.as_view(), name='listar-flujos-pendientes-comercial'),
    path('comercial/generar-pdf/<str:obligacion>/', GenerarPDF.as_view(), name='generar-pdf-comercial'),
    path('comercial/historial/', historial_pdfs, name='historial_pdfs_comercial'),
]
