from rest_framework.views import APIView
from django.http import HttpResponse, JsonResponse
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
from itertools import groupby
from operator import itemgetter

logger = logging.getLogger(__name__)

def _get_oracle_connection():
    """Establishes and returns an Oracle database connection."""
    db = settings.DATABASES['oracle']
    dsn = f"{db['HOST']}:{db['PORT']}/{db['NAME']}"
    return oracledb.connect(user=db['USER'], password=db['PASSWORD'], dsn=dsn)

def _fetch_all_flows_from_db():
    """
    Calls the SP_PLANPAGOS stored procedure and returns all flows
    grouped by K_FLUJO.
    """
    now = datetime.now()
    fecha_actual = now.strftime("%Y/%m/%d %H:%M:%S")
    
    with _get_oracle_connection() as conn:
        with conn.cursor() as cursor:
            ref_cursor_out = cursor.var(oracledb.CURSOR)
            parametros_completos = [fecha_actual, ref_cursor_out]
            cursor.callproc('SP_PLANPAGOS', parametros_completos)
            cur = ref_cursor_out.getvalue()

            if not cur:
                return []

            cols = [c[0] for c in cur.description]
            all_rows = [dict(zip(cols, row)) for row in cur]
            
            # Ensure K_EMAIL is selected and handled, default to a placeholder if not present
            for row in all_rows:
                if 'K_EMAIL' not in row:
                    row['K_EMAIL'] = 'no-email@example.com'

            grouped_data = groupby(sorted(all_rows, key=itemgetter('K_FLUJO')), key=itemgetter('K_FLUJO'))

            data = []
            for k_flujo, group in grouped_data:
                flujo_rows = list(group)
                first_row = flujo_rows[0]
                flujo_dict = {
                    'K_FLUJO': k_flujo,
                    'N_PARAME': first_row.get('N_PARAME'),
                    'NNASOCIA': first_row.get('NNASOCIA'),
                    'K_EMAIL': first_row.get('K_EMAIL'),
                    'PLAN_PAGO': [
                        {col: row.get(col) for col in cols} for row in flujo_rows
                    ]
                }
                data.append(flujo_dict)
            return data

class ListPendingFlowsView(APIView):
    @swagger_auto_schema(
        operation_description="""Consulta la base de datos y devuelve una lista JSON de los flujos de planes de pago pendientes.""",
        responses={
            200: openapi.Response('Lista de flujos pendientes.', schema=openapi.Schema(
                type=openapi.TYPE_ARRAY,
                items=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'K_FLUJO': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'K_EMAIL': openapi.Schema(type=openapi.TYPE_STRING),
                        'NNASOCIA': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            )),
            500: 'Error en la consulta a la base de datos.'
        }
    )
    def get(self, request):
        try:
            all_flows = _fetch_all_flows_from_db()
            # Return a simplified list for n8n to loop through
            summary_list = [
                {
                    "K_FLUJO": flow.get("K_FLUJO"),
                    "K_EMAIL": flow.get("K_EMAIL"),
                    "NNASOCIA": flow.get("NNASOCIA")
                }
                for flow in all_flows
            ]
            return JsonResponse(summary_list, safe=False, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error in ListPendingFlowsView: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GeneratePdfView(APIView):

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
        p.setFont("Helvetica-Bold", 16)
        p.drawCentredString(width / 2.0, 790, "LIQUIDACIÓN DE CRÉDITO")
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
        plan_pago_data = flujo_data.get('PLAN_PAGO', [])
        if not plan_pago_data:
            p.setFont("Helvetica", 10)
            p.drawString(60, 560, "No hay datos del plan de pago disponibles.")
            return
        headers = ["No.", "Fecha", "Abono Capital", "Abono Interés", "Seguro", "Otros", "Capitalización", "Valor Cuota", "Saldo"]
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
        table.wrapOn(p, width, 0)
        table.drawOn(p, 50, 560 - len(table_data) * 15)

    @swagger_auto_schema(
        operation_description="""Genera un PDF para un único flujo de plan de pagos especificado por su ID.""",
        manual_parameters=[
            openapi.Parameter('flujo_id', openapi.IN_PATH, description="ID del flujo a generar.", type=openapi.TYPE_INTEGER, required=True)
        ],
        responses={
            200: openapi.Response('PDF del plan de pagos generado exitosamente.', schema=openapi.Schema(type=openapi.TYPE_FILE)),
            404: 'Flujo no encontrado.',
            500: 'Error en la consulta a la base de datos o en la generación del PDF.'
        }
    )
    def get(self, request, flujo_id):
        try:
            all_flows = _fetch_all_flows_from_db()
            
            target_flujo = None
            for flow in all_flows:
                if flow.get('K_FLUJO') == flujo_id:
                    target_flujo = flow
                    break
            
            if not target_flujo:
                return JsonResponse({"error": "Flujo no encontrado"}, status=status.HTTP_404_NOT_FOUND)

            buffer = io.BytesIO()
            p = canvas.Canvas(buffer, pagesize=letter)
            width, height = letter
            
            # Generate the single PDF page for the target flow
            parame_data = self._parse_n_parame(target_flujo.get('N_PARAME', ''))
            self._draw_header(p, width, target_flujo, parame_data)
            self._draw_payment_table(p, width, target_flujo)
            
            p.save()
            buffer.seek(0)

            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="plan_pago_{flujo_id}_{datetime.now().strftime("%Y%m%d")}.pdf"'
            return response

        except Exception as e:
            logger.error(f"Error en GeneratePdfView para flujo_id {flujo_id}: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
