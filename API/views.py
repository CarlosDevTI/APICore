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
import textwrap

logger = logging.getLogger(__name__)

def _get_oracle_connection():
    """Establecer y retornar la conexión a la base de datos ORACLE."""
    db = settings.DATABASES['oracle']
    dsn = f"{db['HOST']}:{db['PORT']}/{db['NAME']}"
    return oracledb.connect(user=db['USER'], password=db['PASSWORD'], dsn=dsn)

def _filtrar_flujos(cedula=None):
    """
    Llama al procedimiento almacenado SP_PLANPAGOS y retorna los flujos.
    Si se proporciona una cédula, filtra los resultados para esa cédula.
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
            
            # Filtrar por cédula si se proporciona, comparando como strings para evitar errores de tipo.
            if cedula:
                all_rows = [row for row in all_rows if str(row.get('CEDULA', '')) == str(cedula)]

            if not all_rows:
                return []
            
            for row in all_rows:
                if 'MAIL' not in row or not row['MAIL']:
                    row['MAIL'] = 'no-email@example.com'

            data = []
            for row in all_rows:
                plan_pago = []
                # Separar los valores de las columnas por punto y coma
                nos = str(row.get('NO', '')).split(';')
                fechas = str(row.get('FECHA', '')).split(';')
                abonos_capital = str(row.get('ABONO_CAPITAL', '')).split(';')
                abonos_interes = str(row.get('ABONO_INTERES', '')).split(';')
                seguros_vida = str(row.get('SEGURO_VIDA', '')).split(';')
                otros_conceptos = str(row.get('OTROS_CONCEPTOS', '')).split(';')
                capitalizaciones = str(row.get('CAPITALIZACION', '')).split(';')
                valores_cuota = str(row.get('VALOR_CUOTA', '')).split(';')
                saldos_parcial = str(row.get('SALDO_PARCIAL', '')).split(';')

                num_cuotas = len(nos)
                for i in range(num_cuotas):
                    plan_pago.append({
                        'CUOTA': nos[i] if i < len(nos) else '',
                        'FECHA': fechas[i] if i < len(fechas) else '',
                        'ABONO_CAPITAL': abonos_capital[i] if i < len(abonos_capital) else '',
                        'ABONO_INTERES': abonos_interes[i] if i < len(abonos_interes) else '',
                        'SEGURO_VIDA': seguros_vida[i] if i < len(seguros_vida) else '',
                        'OTROS_CONCEPTOS': otros_conceptos[i] if i < len(otros_conceptos) else '',
                        'CAPITALIZACION': capitalizaciones[i] if i < len(capitalizaciones) else '',
                        'VALOR_CUOTA': valores_cuota[i] if i < len(valores_cuota) else '',
                        'SALDO_PARCIAL': saldos_parcial[i] if i < len(saldos_parcial) else '',
                    })
                
                row['PLAN_PAGO'] = plan_pago
                data.append(row)
            return data

class ListarFlujosPendientes(APIView):
    @swagger_auto_schema(
        operation_description="""Consulta la base de datos y devuelve una lista JSON de los flujos de planes de pago pendientes.""",
        responses=    {
            200: openapi.Response('Lista de flujos pendientes.', schema=openapi.Schema(
                type=openapi.TYPE_ARRAY,
                items=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'CEDULA': openapi.Schema(type=openapi.TYPE_STRING),
                        'NOMBRE': openapi.Schema(type=openapi.TYPE_STRING),
                        'MAIL': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            )),
            500: 'Error en la consulta a la base de datos.'
        }
    )
    def get(self, request):
        try:
            all_flows = _filtrar_flujos()
            #! Filtrar solo los que tengan email válido
            all_flows = [
                flow for flow in all_flows 
                if flow.get("MAIL") and flow.get("MAIL") != "no-email@example.com"
            ]
            summary_list = [
                {
                    "CEDULA": flow.get("CEDULA"),
                    "NOMBRE": flow.get("NOMBRE"),
                    "MAIL": flow.get("MAIL"),
                }
                for flow in all_flows
            ]
            return JsonResponse(summary_list, safe=False, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en la función ListarFlujosPendientes: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#? GENERAR PDF PARA UN ÚNICO FLUJO
class GenerarPDF(APIView):

    def _format_colombian(self, num_str):
        """Formatea un string numérico a formato de miles colombiano (puntos)."""
        if num_str is None or str(num_str).strip() == '':
            return '0'
        try:
            # Limpiar el string de formatos existentes y convertir a número
            cleaned_str = str(num_str).replace('.', '').replace(',', '.')
            number = float(cleaned_str)
            # Formatear con puntos como separadores de miles, sin decimales
            return f'{int(number):,}'.replace(',', '.')
        except (ValueError, TypeError):
            return str(num_str) # Devuelve el original si no es un número

    def _draw_header(self, p, width, height):
        """Dibuja el encabezado principal"""
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'Logo.png')
        p.drawImage(logo_path, 40, height - 50, width=120, height=50, preserveAspectRatio=True, anchor='w', mask='auto')
        p.setFont("Helvetica-Bold", 18)
        p.drawCentredString(width / 2.0, height - 40, "LIQUIDACIÓN DE CRÉDITO")

    def _draw_client_data(self, p, width, y_start, flujo_data):
        """Dibuja la sección de datos del cliente con espaciado y fuentes mejoradas."""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Datos del cliente")
        
        y = y_start - 25
        line_height = 22
        col_1_label = 50
        col_1_value = 160
        col_2_label = 320
        col_2_value = 430
        
        # Fila 1
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Identificación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('CEDULA', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Nombre:")
        p.setFont("Helvetica", 9.5)
        
        nombre = flujo_data.get('NOMBRE', '')
        extra_y_offset = 0
        max_len = 30  # Máximo de caracteres por línea para el nombre
        if len(nombre) > max_len:
            lines = textwrap.wrap(nombre, width=max_len)
            p.drawString(col_2_value, y, lines[0])
            if len(lines) > 1:
                extra_y_offset = 14  # Espacio vertical extra para la segunda línea
                y -= extra_y_offset
                p.drawString(col_2_value, y, " ".join(lines[1:]))
        else:
            p.drawString(col_2_value, y, nombre)

        # Fila 2
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Fecha expedición:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FECHA_EXPEDICION', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Lugar expedición:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('LUGAR_EXPEDICION', 'N/A'))

        # Fila 3
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Código:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('CODIGO', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Dirección:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('DIRECCION', ''))

        # Fila 4
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Ciudad:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('CIUDAD', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Departamento:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('DEPARTAMENTO', ''))

        # Fila 5
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Dependencia:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('DEPENDENCIA', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Ubicación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('UBICACION', ''))
        
        return y - 25 - extra_y_offset

    def _draw_obligation_data(self, p, width, y_start, flujo_data):
        """Dibuja la sección de datos de la obligación con espaciado y fuentes mejoradas."""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Datos de la obligación")
        
        y = y_start - 25
        line_height = 22
        col_1_label = 50
        col_1_value = 160
        col_2_label = 320
        col_2_value = 430

        # Fila 1
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Solicitud:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('SOLICITUD', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Obligación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('OBLIGACION', 'N/A'))

        # Fila 2
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Número del pagaré:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('NUM_PAGARE', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Modalidad:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('MODALIDAD', ''))

        # Fila 3
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Destinación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('DESTINACION', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Medio de pago:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('MEDIO_PAGO', ''))

        # Fila 4
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Linea:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('LINEA', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Fecha de solicitud:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('FECHA_SOLICITUD', 'N/A'))

        # Fila 5
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Fecha de aprobación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FECHA_APROBACION', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Fecha de desembolso:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('FECHA_DESEMBOLSO', 'N/A'))

        # Fila 6
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "T.E.A:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('TEA', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "T.N.A.M.V:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('TNAMV', 'N/A'))

        # Fila 7
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Tasa Periódica:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('TASA_PERIODICA', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Tasa de usura:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('TASA_USURA', 'N/A'))

        # Fila 8
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Otros conceptos:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('OTROS_CONCEPTOS_INFO', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Seg. Vida:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('SEG_VIDA_PERCENT', 'N/A'))

        # Fila 9
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Forma de pago:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FORMA_PAGO', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Tipo de tasa:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('TIPO_TASA', 'Fija'))

        # Fila 10
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Fecha primera cuota:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FECHA_PRIMERA_CUOTA', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Fecha última cuota:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('FECHA_ULTIMA_CUOTA', 'N/A'))

        # Fila 11
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Número de cuotas:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, str(flujo_data.get('NUM_CUOTAS', 'N/A')))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Valor de la cuota:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, self._format_colombian(flujo_data.get('VALORCUOTA', 'N/A')))

        # Fila 12
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Día de vencimiento:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, str(flujo_data.get('DIA_VENCIMIENTO', 'N/A')))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Periodicidad de pago:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('PERIODICIDAD', 'Mensual'))

        # Fila 13
        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Garantía:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('GARANTIA', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Clasificación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('CLASIFICACION', 'Consumo'))
        y - 10
        return y - 25

    def _draw_liquidation_detail(self, p, width, y_start, flujo_data):
        """Dibuja la tabla de detalle de liquidación"""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Detalle de liquidación")
        
        y_pos = y_start - 5

        liquidacion_data = [
            {'concepto': 'Monto', 'obligacion': self._format_colombian(flujo_data.get('MONTO', '0')), 'debito': '0', 'credito': ''},
            {'concepto': 'Intereses Anticipados de Ajuste al ciclo', 'obligacion': '', 'debito': '0', 'credito': self._format_colombian(flujo_data.get('INT_ANTICIPADOS', '0'))},
            {'concepto': 'Obligaciones de cartera financiera que recoge', 'obligacion': flujo_data.get('OBLIG_RECOGE', ''), 'debito': '0', 'credito': self._format_colombian(flujo_data.get('OBLIG_RECOGE_VALOR', '0'))},
            {'concepto': 'Neto a Girar', 'obligacion': '', 'debito': '0', 'credito': self._format_colombian(flujo_data.get('NETO_GIRAR', '0'))}
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
            ('FONTSIZE', (0, 0), (-1, 0), 9.5),
            ('FONTSIZE', (0, 1), (-1, -1), 9.5),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ])
        table.setStyle(style)
        
        w, h = table.wrapOn(p, width - 80, y_pos)
        table.drawOn(p, 40, y_pos - h)
        
        return y_pos - h - 20

    def _draw_payment_table(self, p, width, y_start, flujo_data, start_row=0, end_row=None):
        """Dibuja la tabla del ciclo de pago con posicionamiento corregido y paginación."""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 80, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Ciclo de pago")
        
        y_pos = y_start - 5

        plan_pago_data = flujo_data.get('PLAN_PAGO', [])
        if not plan_pago_data:
            p.setFont("Helvetica", 9.5)
            p.drawString(50, y_pos - 15, "No hay datos del plan de pago disponibles.")
            return y_pos - 30

        if end_row is None:
            end_row = len(plan_pago_data)
        
        data_slice = plan_pago_data[start_row:end_row]

        headers = ["No.", "Fecha", "Abono\nCapital", "Abono\nInterés", "Seguro de\nvida", 
                   "Otros\nconceptos", "Capitalización", "Valor Cuota", "Saldo\nparcial"]
        col_names = ['CUOTA', 'FECHA', 'ABONO_CAPITAL', 'ABONO_INTERES', 'SEGURO_VIDA', 
                     'OTROS_CONCEPTOS', 'CAPITALIZACION', 'VALOR_CUOTA', 'SALDO_PARCIAL']
        
        table_data = [headers]
        
        for row in data_slice:
            formatted_row = []
            for idx, col_name in enumerate(col_names):
                value = row.get(col_name, '')
                if idx > 1:  # Formatear columnas numéricas
                    formatted_row.append(self._format_colombian(value))
                else:
                    formatted_row.append(str(value))
            table_data.append(formatted_row)

        is_last_slice = (end_row >= len(plan_pago_data))
        if is_last_slice and len(plan_pago_data) > 0:
            totales = ['Totales', '']
            for col_idx, col_name in enumerate(col_names):
                if col_idx > 1:
                    try:
                        total = sum(float(str(row.get(col_name, 0)).replace('.', '').replace(',', '.')) for row in plan_pago_data if row.get(col_name))
                        totales.append(self._format_colombian(total))
                    except (ValueError, TypeError):
                        totales.append('0')
            totales[-1] = '' # El saldo parcial no se totaliza
            table_data.append(totales)
        
        col_widths = [30, 60, 60, 60, 55, 55, 60, 60, 70]
        table = Table(table_data, colWidths=col_widths)
        
        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#d9d9d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 4),
            ('BACKGROUND', (0, 1), (-1, -2), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8.5),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ]
        
        if is_last_slice and len(plan_pago_data) > 0:
            style_commands.extend([
                ('BACKGROUND', (0, -1), (-1, -1), HexColor('#f0f0f0')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ])
        
        table.setStyle(TableStyle(style_commands))
        
        w, h = table.wrapOn(p, width - 80, y_pos)
        table.drawOn(p, 40, y_pos - h)
        
        return y_pos - h - 20

    def _draw_footer(self, p, width, y_position):
        """Dibuja el pie de página con firmas"""
        if y_position < 100:
            p.showPage()
            y_position = 750
        
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_position, width - 80, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_position + 7, "Firmas")
        
        y = y_position - 40
        p.setFont("Helvetica-Bold", 9.5)
        p.line(50, y, 250, y)
        p.drawString(50, y - 12, "Nombre del deudor")
        
        p.line(350, y, 550, y)
        p.drawString(350, y - 12, "Firma")

    def _draw_page_number(self, p, width, height, page_num, total_pages):
        """Dibuja el número de página"""
        p.setFont("Helvetica", 9.5)
        p.drawRightString(width - 40, 30, f"Página: {page_num}")

    @swagger_auto_schema(
        operation_description="""Genera un PDF para un único flujo de plan de pagos especificado por su ID.""",
        manual_parameters=[
            openapi.Parameter('cedula', openapi.IN_PATH, description="Cédula del cliente a generar.", 
                            type=openapi.TYPE_STRING, required=True)
        ],
        responses={ 
            200: openapi.Response('PDF del plan de pagos generado exitosamente.', 
                                schema=openapi.Schema(type=openapi.TYPE_FILE)),
            404: 'Flujo no encontrado.',
            500: 'Error en la consulta a la base de datos o en la generación del PDF.'
        }
    )
    def get(self, request, cedula):
        try:
            flujos_filtrados = _filtrar_flujos(cedula=cedula)
            
            if not flujos_filtrados:
                return JsonResponse({"error": "Flujo no encontrado para la cédula proporcionada"}, status=status.HTTP_404_NOT_FOUND)

            target_flujo = flujos_filtrados[0]

            buffer = io.BytesIO()
            p = canvas.Canvas(buffer, pagesize=letter)
            width, height = letter
            
            # --- Page 1 ---
            self._draw_header(p, width, height)
            
            y_pos = height - 80
            y_pos = self._draw_client_data(p, width, y_pos, target_flujo)
            y_pos -= 15  # Add vertical space
            y_pos = self._draw_obligation_data(p, width, y_pos, target_flujo)
            y_pos -= 25  # Added extra space as requested
            y_pos = self._draw_liquidation_detail(p, width, y_pos, target_flujo)
            
            # --- Payment Plan Pages & Footer ---
            plan_pago_data = target_flujo.get('PLAN_PAGO', [])
            rows_per_page = 30  # Estimated rows per page
            num_rows = len(plan_pago_data)
            
            num_payment_pages = (num_rows + rows_per_page - 1) // rows_per_page
            if num_payment_pages == 0:
                num_payment_pages = 1

            self._draw_page_number(p, width, height, 1)

            page_num = 2
            start_row = 0
            y_pos_after_table = 0
            for i in range(num_payment_pages):
                p.showPage()
                self._draw_header(p, width, height)
                y_pos_page = height - 80
                
                end_row = start_row + rows_per_page
                
                y_pos_after_table = self._draw_payment_table(p, width, y_pos_page, target_flujo, start_row, end_row)
                
                self._draw_page_number(p, width, height, page_num)
                
                start_row = end_row
                page_num += 1

            # --- Signature Section ---
            # Draw footer on the same page as the last table, with a separator.
            # The _draw_footer function will handle creating a new page if needed.
            self._draw_footer(p, width, y_pos_after_table - 25)
            
            p.save()
            buffer.seek(0)

            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="plan_pago_{cedula}_{datetime.now().strftime("%Y%m%d")}.pdf"'
            return response

        except Exception as e:
            logger.error(f"Error en GenerarPDF para cedula {cedula}: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
