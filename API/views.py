from rest_framework.views import APIView
from django.http import HttpResponse
from rest_framework import status
from django.db import connection
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from datetime import datetime
import json
import logging
from django.conf import settings
import oracledb
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.colors import HexColor

logger = logging.getLogger(__name__)

class ValidarView(APIView):

    def _parse_n_parame(self, n_parame_str):
        parts = [p.strip() for p in n_parame_str.split('-')]
        parsed_data = {
            'identificacion': parts[0] if len(parts) > 0 else '',
            'nombre': parts[1] if len(parts) > 1 else '',
            'modalidad': parts[2] if len(parts) > 2 else '',
            'linea': parts[4] if len(parts) > 4 else '',
            'monto': parts[6] if len(parts) > 6 else '0.00',
            'forma_pago': parts[12] if len(parts) > 12 else '',
            'medio_pago': parts[16] if len(parts) > 16 else ''
        }
        return parsed_data

    def _draw_header(self, p, width, flujo_data, parame_data):
        """Dibuja la cabecera y las secciones de datos del cliente/obligación."""
        p.setFont("Helvetica-Bold", 16)
        p.drawCentredString(width / 2.0, 790, "LIQUIDACIÓN DE CRÉDITO")
        #? --- Datos del cliente ---
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(50, 740, width - 100, 20, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 11)
        p.drawString(60, 745, "Datos del cliente")
        p.setFont("Helvetica-Bold", 10)
        p.drawString(60, 720, "Identificación:")
        p.drawString(250, 720, "Nombre:")
        p.setFont("Helvetica", 10)
        p.drawString(140, 720, parame_data.get('identificacion', ''))
        p.drawString(300, 720, parame_data.get('nombre', ''))
        #? --- Datos de la obligación ---
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(50, 680, width - 100, 20, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 11)
        p.drawString(60, 685, "Datos de la obligación")
        p.setFont("Helvetica-Bold", 10)
        p.drawString(60, 660, "Solicitud:")
        p.drawString(250, 660, "Obligación:")
        p.drawString(60, 645, "Modalidad:")
        p.drawString(250, 645, "Monto:")
        p.setFont("Helvetica", 10)
        p.drawString(140, 660, str(flujo_data.get('K_FLUJO', '')))
        p.drawString(310, 660, "N/A")
        p.drawString(140, 645, parame_data.get('modalidad', ''))
        p.drawString(310, 645, parame_data.get('monto', ''))

    def _draw_payment_table(self, p, width, flujo_data):
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(50, 580, width - 100, 20, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 11)
        p.drawString(60, 585, "Ciclo de pago")

        # Asumimos que los detalles de las cuotas vienen en una clave como 'PLAN_PAGO'
        plan_pago_data = flujo_data.get('PLAN_PAGO', [])
        
        if not plan_pago_data:
            p.setFont("Helvetica", 10)
            p.drawString(60, 560, "No hay datos del plan de pago disponibles.")
            return

        # Encabezados de la tabla
        headers = ["No.", "Fecha", "Abono Capital", "Abono Interés", "Seguro", "Otros", "Capitalización", "Valor Cuota", "Saldo"]
        # Nombres de las columnas en los datos
        col_names = ['CUOTA', 'FECHA', 'ABONO_CAPITAL', 'ABONO_INTERES', 'SEGURO_VIDA', 'OTROS_CONCEPTOS', 'CAPITALIZACION', 'VALOR_CUOTA', 'SALDO_PARCIAL']

        table_data = [headers]
        for row in plan_pago_data:
            table_data.append([row.get(col, '') for col in col_names])

        table = Table(table_data, colWidths=[30, 65, 65, 65, 50, 50, 70, 65, 70])

        style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#d9d9d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
        ])
        table.setStyle(style)

        # Dibujar la tabla en el canvas
        table.wrapOn(p, width, 0)
        table.drawOn(p, 50, 560 - len(table_data) * 15) # Ajustar posición vertical

    def _generar_pdf_para_flujo(self, p, width, height, flujo_data):
        #? 1. Parsear N_PARAME
        parame_data = self._parse_n_parame(flujo_data.get('N_PARAME', ''))
        #? 2. Dibujar la cabecera
        self._draw_header(p, width, flujo_data, parame_data)
        self._draw_payment_table(p, width, flujo_data)

    @swagger_auto_schema(
        operation_description="""Consulta la base de datos con la fecha y hora actual y devuelve un PDF con los planes de pago.""",
        responses={
            200: openapi.Response('PDF del plan de pagos generado exitosamente', schema=openapi.Schema(type=openapi.TYPE_FILE)),
            500: 'Error en la consulta a la base de datos o en la generación del PDF'
        }
    )
    def get(self, request):
        """
        Obtiene la fecha/hora actual, llama al SP 'SP_PLANPAGOS' 
        y devuelve un PDF con los planes de pago.
        """
        try:
            now = datetime.now()
            fecha_actual = now.strftime("%Y/%m/%d %H:%M:%S")

            db = settings.DATABASES['oracle']
            dsn = f"{db['HOST']}:{db['PORT']}/{db['NAME']}"

            with oracledb.connect(user=db['USER'], password=db['PASSWORD'], dsn=dsn) as conn:
                with conn.cursor() as cursor:
                    # Simulación de datos para prueba sin BD
                    # Descomentar para probar sin conexión a la base de datos
                    # data = [
                    #     {
                    #         'K_FLUJO': 15384597, 
                    #         'N_PARAME': '31306514 - PIZA BETANCOURT KAREN GUISETH - 112 - Libre Inversion - 300 - Libre Inversion - 130,000,000.00',
                    #         'PLAN_PAGO': [
                    #             {'CUOTA': 1, 'FECHA': '2025-08-21', 'ABONO_CAPITAL': 1000, 'ABONO_INTERES': 500, 'SEGURO_VIDA': 50, 'OTROS_CONCEPTOS': 0, 'CAPITALIZACION': 100, 'VALOR_CUOTA': 1650, 'SALDO_PARCIAL': 129000},
                    #             {'CUOTA': 2, 'FECHA': '2025-09-21', 'ABONO_CAPITAL': 1010, 'ABONO_INTERES': 490, 'SEGURO_VIDA': 50, 'OTROS_CONCEPTOS': 0, 'CAPITALIZACION': 100, 'VALOR_CUOTA': 1650, 'SALDO_PARCIAL': 127990},
                    #         ]
                    #     }
                    # ]
                    ref_cursor_out = cursor.var(oracledb.CURSOR)
                    parametros_completos = [fecha_actual, ref_cursor_out]
                    cursor.callproc('SP_PLANPAGOS', parametros_completos)
                    cur = ref_cursor_out.getvalue()

                    data = []
                    if cur:
                        # Esta lógica asume que el SP devuelve una fila por flujo, y una de las columnas
                        # (ej. 'PLAN_PAGO') es un CURSOR o un CLOB JSON con las cuotas.
                        # Esto necesita ser ajustado a la estructura real que devuelve el SP.
                        cols = [c[0] for c in cur.description]
                        # Tentativa: Asumimos que el SP devuelve una fila por cuota y las agrupamos por K_FLUJO
                        from itertools import groupby
                        from operator import itemgetter

                        all_rows = [dict(zip(cols, row)) for row in cur]
                        grouped_data = groupby(sorted(all_rows, key=itemgetter('K_FLUJO')), key=itemgetter('K_FLUJO'))

                        data = []
                        for k_flujo, group in grouped_data:
                            flujo_rows = list(group)
                            first_row = flujo_rows[0]
                            flujo_dict = {
                                'K_FLUJO': k_flujo,
                                'N_PARAME': first_row.get('N_PARAME'),
                                'NNASOCIA': first_row.get('NNASOCIA'),
                                # ... otros campos del flujo
                                'PLAN_PAGO': [
                                    {col: row.get(col) for col in cols} for row in flujo_rows
                                ]
                            }
                            data.append(flujo_dict)

                    buffer = io.BytesIO()
                    p = canvas.Canvas(buffer, pagesize=letter)
                    width, height = letter

                    if not data:
                        p.drawString(100, 750, "No se encontraron flujos para la fecha y hora consultada.")
                    else:
                        for flujo in data:
                            self._generar_pdf_para_flujo(p, width, height, flujo)
                            p.showPage()
                    
                    p.save()
                    buffer.seek(0)

                    response = HttpResponse(buffer, content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="plan_pagos_{now.strftime("%Y%m%d_%H%M%S")}.pdf"'
                    return response

        except Exception as e:
            logger.error(f"Error en la vista ValidarView: {e}", exc_info=True)
            return HttpResponse(
                json.dumps({"error": f"Ha ocurrido un error: {str(e)}"}),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content_type='application/json'
            )
