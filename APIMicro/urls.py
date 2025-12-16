from django.urls import path
from .views import ListarFlujosPendientes, GenerarPDF, historial_pdfs

urlpatterns = [
    path('microcredito/listar-flujos-pendientes/', ListarFlujosPendientes.as_view(), name='listar-flujos-pendientes-microcredito'),
    path('microcredito/generar-pdf/<str:obligacion>/', GenerarPDF.as_view(), name='generar-pdf-microcredito'),
    path('microcredito/historial/', historial_pdfs, name='historial_pdfs_microcredito'),
]
