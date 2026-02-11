from django.urls import path
from .views import ListarFlujosPendientes, GenerarPDF, GenerarPDFContingencia, historial_pdfs

urlpatterns = [
    path('consumo/listar-flujos-pendientes/', ListarFlujosPendientes.as_view(), name='listar-flujos-pendientes-consumo'),
    path('consumo/generar-pdf/<str:obligacion>/', GenerarPDF.as_view(), name='generar-pdf-consumo'),
    path('consumo/generar-pdf-contingencia/<str:obligacion>/', GenerarPDFContingencia.as_view(), name='generar-pdf-consumo-contingencia'),
    path('consumo/historial/', historial_pdfs, name='historial_pdfs_consumo'),
]
