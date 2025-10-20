from rest_framework.views import APIView
from django.http import HttpResponse, JsonResponse
from rest_framework import status
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from datetime import datetime
import logging
import os
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
    """Establecer y retornar la conexión a la base de datos ORACLE."""
    db = settings.DATABASES['oracle']
    dsn = f"{db['HOST']}:{db['PORT']}/{db['NAME']}"
    return oracledb.connect(user=db['USER'], password=db['PASSWORD'], dsn=dsn)

def _filtrar_flujos():
    """
    Llamar al procedimiento almacenado SP_PLANPAGOS y retornar todos los flujos
    agrupados por K_FLUJO.
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
            
            # Asegurar que MAIL esté seleccionado y manejado, por defecto a un marcador de posición si no está presente
            for row in all_rows:
                if 'MAIL' not in row:
                    row['MAIL'] = 'no-email@example.com'

            # Agrupar los datos por K_FLUJO
            grouped_data = groupby(sorted(all_rows, key=itemgetter('K_FLUJO')), key=itemgetter('K_FLUJO'))

            data = []
            for k_flujo, group in grouped_data:
                flujo_rows = list(group)
                first_row = flujo_rows[0]
                flujo_dict = {
                    'K_FLUJO': k_flujo,
                    'N_PARAME': first_row.get('N_PARAME'),
                    'NNASOCIA': first_row.get('NNASOCIA'),
                    'MAIL': first_row.get('MAIL'),
                    'PLAN_PAGO': [
                        {col: row.get(col) for col in cols} for row in flujo_rows
                    ]
                }
                data.append(flujo_dict)
            return data

class ListarFlujosPendientes(APIView):
    @swagger_auto_schema(
        operation_description="""Consulta la base de datos y devuelve una lista JSON de los flujos de planes de pago pendientes.""",
        responses={
            200: openapi.Response('Lista de flujos pendientes.', schema=openapi.Schema(
                type=openapi.TYPE_ARRAY,
                items=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'K_FLUJO': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'MAIL': openapi.Schema(type=openapi.TYPE_STRING),
                        'NNASOCIA': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            )),
            500: 'Error en la consulta a la base de datos.'
        }
    )
    def get(self, request):
        try:
            all_flows = _filtrar_flujos()
            # Retornar una lista simplificada para que n8n pueda iterar
            summary_list = [
                {
                    "K_FLUJO": flow.get("K_FLUJO"),
                    "MAIL": flow.get("MAIL"),
                    "NNASOCIA": flow.get("NNASOCIA")
                }
                for flow in all_flows
            ]
            return JsonResponse(summary_list, safe=False, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en la función ListarFlujosPendientes: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#? GENERAR PDF PARA UN ÚNICO FLUJO
class GenerarPDF(APIView):

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

    def _draw_header(self, p, width, height):
        """Dibuja el encabezado principal"""
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'Logo.png')
        p.drawImage(logo_path, 40, height - 50, width=120, height=50, preserveAspectRatio=True, anchor='w', mask='auto')
        p.setFont("Helvetica-Bold", 18)
        p.drawCentredString(width / 2.0, height - 40, "LIQUIDACIÓN DE CRÉDITO")
        
    def _draw_client_data(self, p, width, y_start, flujo_data, parame_data):
        """Dibuja la sección de datos del cliente"""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 18, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 5, "Datos del cliente")
        
        y = y_start - 20
        p.setFont("Helvetica-Bold", 8)
        
        # Primera fila
        p.drawString(50, y, "Identificación:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, parame_data.get('identificacion', ''))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Fecha de expedición")
        p.drawString(220, y - 10, "identificación:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y - 5, flujo_data.get('FECHA_EXPEDICION', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(390, y, "Lugar expedición")
        p.drawString(390, y - 10, "identificación:")
        p.setFont("Helvetica", 8)
        p.drawString(470, y - 5, flujo_data.get('LUGAR_EXPEDICION', 'N/A'))
        
        # Segunda fila
        y -= 25
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Nombre:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, parame_data.get('nombre', ''))
        
        # Tercera fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Código:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('CODIGO', ''))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Dirección:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('DIRECCION', ''))
        
        # Cuarta fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Ciudad:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('CIUDAD', ''))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Departamento:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('DEPARTAMENTO', ''))
        
        # Quinta fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Dependencia:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('DEPENDENCIA', ''))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Ubicación:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('UBICACION', ''))
        
        return y - 25

    def _draw_obligation_data(self, p, width, y_start, flujo_data, parame_data):
        """Dibuja la sección de datos de la obligación"""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 18, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 5, "Datos de la obligación")
        
        y = y_start - 20
        p.setFont("Helvetica-Bold", 8)
        
        # Primera fila
        p.drawString(50, y, "Solicitud:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, str(flujo_data.get('K_FLUJO', '')))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Obligación:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('OBLIGACION', 'N/A'))
        
        # Segunda fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Número del pagaré:")
        p.setFont("Helvetica", 8)
        p.drawString(145, y, flujo_data.get('NUM_PAGARE', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Modalidad:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, parame_data.get('modalidad', ''))
        
        # Tercera fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Destinación:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('DESTINACION', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Medio de pago:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, parame_data.get('medio_pago', ''))
        
        # Cuarta fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Linea:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, parame_data.get('linea', ''))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Fecha de solicitud:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('FECHA_SOLICITUD', 'N/A'))
        
        # Quinta fila - Fechas
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Fecha de aprobación:")
        p.setFont("Helvetica", 8)
        p.drawString(145, y, flujo_data.get('FECHA_APROBACION', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Fecha de desembolso:")
        p.setFont("Helvetica", 8)
        p.drawString(330, y, flujo_data.get('FECHA_DESEMBOLSO', 'N/A'))
        
        # Sexta fila - Tasas
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "T.E.A:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('TEA', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "T.N.A.M.V:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('TNAMV', 'N/A'))
        
        # Séptima fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Tasa Periódica:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('TASA_PERIODICA', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Tasa de usura:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('TASA_USURA', 'N/A'))
        
        # Octava fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Otros conceptos:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('OTROS_CONCEPTOS_INFO', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Seg. Vida:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('SEG_VIDA_PERCENT', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(400, y, "Tipo de tasa:")
        p.setFont("Helvetica", 8)
        p.drawString(470, y, flujo_data.get('TIPO_TASA', 'Fija'))
        
        # Novena fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Factor de variabilidad:")
        p.setFont("Helvetica", 8)
        p.drawString(155, y, flujo_data.get('FACTOR_VARIABILIDAD', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Forma de pago:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, parame_data.get('forma_pago', ''))
        
        # Décima fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Fecha primera cuota:")
        p.setFont("Helvetica", 8)
        p.drawString(145, y, flujo_data.get('FECHA_PRIMERA_CUOTA', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Fecha última cuota:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('FECHA_ULTIMA_CUOTA', 'N/A'))
        
        # Onceava fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Número de cuotas:")
        p.setFont("Helvetica", 8)
        p.drawString(145, y, str(flujo_data.get('NUM_CUOTAS', 'N/A')))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Valor de la cuota:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('VALOR_CUOTA', 'N/A'))
        
        # Doceava fila
        y -= 15
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Día de vencimiento de la")
        p.drawString(50, y - 10, "cuota:")
        p.setFont("Helvetica", 8)
        p.drawString(145, y - 5, str(flujo_data.get('DIA_VENCIMIENTO', 'N/A')))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Periodicidad de pago:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('PERIODICIDAD', 'Mensual'))
        
        # Treceava fila
        y -= 20
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Garantía:")
        p.setFont("Helvetica", 8)
        p.drawString(125, y, flujo_data.get('GARANTIA', 'N/A'))
        
        p.setFont("Helvetica-Bold", 8)
        p.drawString(220, y, "Clasificación:")
        p.setFont("Helvetica", 8)
        p.drawString(310, y, flujo_data.get('CLASIFICACION', 'Consumo'))
        
        return y - 25

    def _draw_liquidation_detail(self, p, width, y_start, flujo_data, parame_data):
        """Dibuja la tabla de detalle de liquidación"""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 18, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 5, "Detalle de liquidación")
        
        liquidacion_data = flujo_data.get('DETALLE_LIQUIDACION', [])
        
        if not liquidacion_data:
            # Datos por defecto basados en el ejemplo
            liquidacion_data = [
                {'concepto': 'Monto', 'obligacion': parame_data.get('monto', '0'), 'debito': '0', 'credito': ''},
                {'concepto': 'Intereses Anticipados de Ajuste al ciclo', 'obligacion': '', 'debito': '0', 'credito': flujo_data.get('INT_ANTICIPADOS', '0')},
                {'concepto': 'Obligaciones de cartera financiera que recoge', 'obligacion': flujo_data.get('OBLIG_RECOGE', ''), 'debito': '0', 'credito': flujo_data.get('OBLIG_RECOGE_VALOR', '0')},
                {'concepto': 'Neto a Girar', 'obligacion': '', 'debito': '0', 'credito': flujo_data.get('NETO_GIRAR', '0')}
            ]
        
        table_data = [['Concepto', 'Obligación', 'Débito', 'Crédito']]
        
        for item in liquidacion_data:
            table_data.append([
                item.get('concepto', ''),
                item.get('obligacion', ''),
                item.get('debito', ''),
                item.get('credito', '')
            ])
        
        table = Table(table_data, colWidths=[280, 100, 80, 80])
        style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#d9d9d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ])
        table.setStyle(style)
        
        table.wrapOn(p, width, 0)
        table_height = len(table_data) * 15 + 10
        table.drawOn(p, 40, y_start - table_height - 20)
        
        return y_start - table_height - 40

    def _draw_payment_table(self, p, width, y_start, flujo_data):
        """Dibuja la tabla del ciclo de pago"""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 18, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 5, "Ciclo de pago")
        
        plan_pago_data = flujo_data.get('PLAN_PAGO', [])
        if not plan_pago_data:
            p.setFont("Helvetica", 8)
            p.drawString(50, y_start - 20, "No hay datos del plan de pago disponibles.")
            return y_start - 40
        
        headers = ["No.", "Fecha", "Abono\nCapital", "Abono\nInterés", "Seguro de\nvida", 
                   "Otros\nconceptos", "Capitalización", "Valor Cuota", "Saldo\nparcial"]
        col_names = ['CUOTA', 'FECHA', 'ABONO_CAPITAL', 'ABONO_INTERES', 'SEGURO_VIDA', 
                     'OTROS_CONCEPTOS', 'CAPITALIZACION', 'VALOR_CUOTA', 'SALDO_PARCIAL']
        
        table_data = [headers]
        
        for row in plan_pago_data:
            table_data.append([str(row.get(col, '')) for col in col_names])
        
        # Calcular totales
        if len(table_data) > 1:
            totales = ['Totales', '']
            for col in col_names[2:]:
                total = sum(float(str(row.get(col, 0)).replace(',', '')) for row in plan_pago_data if row.get(col))
                totales.append(f"{total:,.0f}")
            totales[-1] = ''  # El saldo final no se suma
            table_data.append(totales)
        
        col_widths = [30, 65, 60, 60, 50, 50, 65, 60, 60]
        table = Table(table_data, colWidths=col_widths)
        
        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#d9d9d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 4),
            ('BACKGROUND', (0, 1), (-1, -2), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
        ]
        
        # Resaltar fila de totales
        if len(table_data) > 2:
            style_commands.extend([
                ('BACKGROUND', (0, -1), (-1, -1), HexColor('#f0f0f0')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ])
        
        table.setStyle(TableStyle(style_commands))
        
        table.wrapOn(p, width, 0)
        table_height = len(table_data) * 12 + 20
        table.drawOn(p, 40, y_start - table_height - 20)
        
        return y_start - table_height - 40

    def _draw_footer(self, p, width, y_position):
        """Dibuja el pie de página con firmas"""
        if y_position < 100:
            p.showPage()
            y_position = 750
        
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_position, width - 80, 18, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_position + 5, "Firmas")
        
        y = y_position - 30
        p.setFont("Helvetica-Bold", 8)
        p.drawString(50, y, "Nombre del deudor")
        p.drawString(300, y, "Firma")
        
        p.line(50, y - 30, 200, y - 30)
        p.line(300, y - 30, 500, y - 30)

    def _draw_page_number(self, p, width, height, page_num, total_pages):
        """Dibuja el número de página"""
        p.setFont("Helvetica", 8)
        p.drawRightString(width - 40, 30, f"Página: {page_num}/{total_pages}")

    @swagger_auto_schema(
        operation_description="""Genera un PDF para un único flujo de plan de pagos especificado por su ID.""",
        manual_parameters=[
            openapi.Parameter('flujo_id', openapi.IN_PATH, description="ID del flujo a generar.", 
                            type=openapi.TYPE_INTEGER, required=True)
        ],
        responses={
            200: openapi.Response('PDF del plan de pagos generado exitosamente.', 
                                schema=openapi.Schema(type=openapi.TYPE_FILE)),
            404: 'Flujo no encontrado.',
            500: 'Error en la consulta a la base de datos o en la generación del PDF.'
        }
    )
    def get(self, request, flujo_id):
        try:
            all_flows = _filtrar_flujos()
            
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
            
            parame_data = self._parse_n_parame(target_flujo.get('N_PARAME', ''))
            
            # Primera página
            self._draw_header(p, width, height)
            
            y_pos = height - 80
            y_pos = self._draw_client_data(p, width, y_pos, target_flujo, parame_data)
            y_pos = self._draw_obligation_data(p, width, y_pos, target_flujo, parame_data)
            y_pos = self._draw_liquidation_detail(p, width, y_pos, target_flujo, parame_data)
            
            self._draw_page_number(p, width, height, 1, 3)
            
            # Segunda página - Ciclo de pago
            p.showPage()
            self._draw_header(p, width, height)
            y_pos = height - 80
            y_pos = self._draw_payment_table(p, width, y_pos, target_flujo)
            self._draw_page_number(p, width, height, 2, 3)
            
            # Tercera página - Firmas
            p.showPage()
            self._draw_header(p, width, height)
            self._draw_footer(p, width, height - 80)
            self._draw_page_number(p, width, height, 3, 3)
            
            p.save()
            buffer.seek(0)

            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="plan_pago_{flujo_id}_{datetime.now().strftime("%Y%m%d")}.pdf"'
            return response

        except Exception as e:
            logger.error(f"Error en GenerarPDF para flujo_id {flujo_id}: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)