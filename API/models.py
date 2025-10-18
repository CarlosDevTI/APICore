from django.db import models

class HistorialPDFs(models.Model):
    """
    Modelo para almacenar el historial de los PDFs de planes de pago generados.
    """
    k_flujo = models.BigIntegerField(help_text="ID del flujo de crédito procesado.")
    fecha_creacion = models.DateTimeField(auto_now_add=True, help_text="Fecha y hora de generación del PDF.")
    pdf_file = models.FileField(upload_to='planes_de_pago/%Y/%m/%d/', help_text="Archivo PDF del plan de pagos.")

    def __str__(self):
        return f"Plan de Pagos para Flujo {self.k_flujo} - {self.fecha_creacion.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        verbose_name = "Historial de PDF"
        verbose_name_plural = "Historiales de PDFs"
        ordering = ['-fecha_creacion']