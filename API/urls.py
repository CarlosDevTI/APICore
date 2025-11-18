from django.urls import path
from .views import ListarFlujosPendientes, GenerarPDF, historial_pdfs, ValidarAsociado

urlpatterns = [
    path('listar-flujos-pendientes/', ListarFlujosPendientes.as_view(), name='listar-flujos-pendientes'),
    path('generar-pdf/<str:obligacion>/', GenerarPDF.as_view(), name='generar-pdf'),
    path('historial/', historial_pdfs, name='historial_pdfs'),
    path('validar-asociado/<str:identificacion>/', ValidarAsociado.as_view(), name='validar-asociado'),]