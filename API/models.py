from django.db import models

class HistorialPDFs(models.Model):
    """
    Modelo para almacenar el historial de los PDFs de planes de pago generados.
    """
    #? Número de obligación unico por crédito, seria el primary key
    obligacion = models.CharField(max_length=50, unique=True, help_text="Número de obligación único por crédito.", default="")
    #? Cédula del cliente asociado al crédito
    cedula_cliente = models.CharField(max_length=20, help_text="Cédula del cliente asociado al crédito.", default="", blank=True)
    #? fecha de creacion y envío del plan de pagos por correo al asociado
    fecha_creacion = models.DateTimeField(auto_now_add=True, help_text="Fecha y hora de generación del PDF y envío al correo.")
    #? Archivo PDF del plan de pagos
    pdf_file = models.FileField(upload_to='planes_de_pago/%Y/%m/%d/', help_text="Archivo PDF del plan de pagos.")

    def __str__(self):
        return f"Plan de Pagos para la obligacion {self.obligacion} - {self.fecha_creacion.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        verbose_name = "Historial de PDF"
        verbose_name_plural = "Historiales de PDFs"
        ordering = ['-fecha_creacion']