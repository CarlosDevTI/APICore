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
from decimal import Decimal, InvalidOperation
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
            # print(all_rows) Impresiones de seguimiento (DESCOMENTAR SI LAS QUIERE VER SOCIO - SAPO)
            
            for row in all_rows:
                for key, value in row.items():
                    if value is None:
                        row[key] = ''

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
                nos = str(row.get('NO', '')).split(';')
                fechas = str(row.get('FECHA', '')).split(';')
                abonos_capital = str(row.get('ABONO_CAPITAL', '')).split(';')
                abonos_interes = str(row.get('ABONO_INTERES', '')).split(';')
                # seguros_vida = str(row.get('SEGURO_VIDA', '')).split(';') EL CAMPO SEGUROS DE VIDA NO EXISTE PORQUE VA INMERSO EN OTROS CONCEPTOS
                otros_conceptos = str(row.get('OTROS_CONCEPTOS', '')).split(';')
                capitalizaciones = str(row.get('CAPITALIZACION', '')).split(';')
                valores_cuota = str(row.get('VALOR_CUOTA', '')).split(';')
                saldos_parcial = str(row.get('SALDO_PARCIAL', '')).split(';')

                num_cuotas = len(nos)
                for i in range(num_cuotas):
                    # Dentro del for i in range(num_cuotas):
                    plan_pago.append({
                        'NO': (nos[i] if i < len(nos) else '').strip(),
                        'FECHA': (fechas[i] if i < len(fechas) else '').strip(),
                        'ABONO_CAPITAL': (abonos_capital[i] if i < len(abonos_capital) else '').strip(),
                        'ABONO_INTERES': (abonos_interes[i] if i < len(abonos_interes) else '').strip(),
                        'OTROS_CONCEPTOS': (otros_conceptos[i] if i < len(otros_conceptos) else '').strip(),
                        'CAPITALIZACION': (capitalizaciones[i] if i < len(capitalizaciones) else '').strip(),
                        'VALOR_CUOTA': (valores_cuota[i] if i < len(valores_cuota) else '').strip(),
                        'SALDO_PARCIAL': (saldos_parcial[i] if i < len(saldos_parcial) else '').strip(),
                    })
                
                row['PLAN_PAGO'] = plan_pago
                # --- FECHAULTIMA: última fecha no vacía
                fechas_no_vacias = [r['FECHA'] for r in plan_pago if r.get('FECHA')]
                row['FECHAULTIMA'] = fechas_no_vacias[-1] if fechas_no_vacias else row.get('FECHAULTIMA', 'N/A')

                # --- VALORCUOTA: toma el de NO == '1' o el primer no vacío como respaldo
                valor_cuota_no1 = next((r.get('VALOR_CUOTA') for r in plan_pago if str(r.get('NO')) == '1' and r.get('VALOR_CUOTA')), None)
                if not valor_cuota_no1:
                    valor_cuota_no1 = next((r.get('VALOR_CUOTA') for r in plan_pago if r.get('VALOR_CUOTA')), None)
                row['VALORCUOTA'] = valor_cuota_no1 or row.get('VALORCUOTA', 'N/A')
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
            all_flows = [flow for flow in all_flows if flow.get("MAIL") and flow.get("MAIL") != "no-email@example.com"]
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

class GenerarPDF(APIView):

    def _parse_number(self, s):
        """
        Convierte una cadena en Decimal entendiendo formatos:
        - '1.234.567' -> 1234567
        - '146004,84' -> 146004.84
        - '146004.84' -> 146004.84
        - '3,791,706'  -> 3791706
        - '' o None    -> 0
        """
        if s is None:
            return Decimal(0)
        s = str(s).strip()
        if not s:
            return Decimal(0)

        # Si tiene ambos separadores, asume . = miles, , = decimal (formato latam)
        if '.' in s and ',' in s:
            s = s.replace('.', '').replace(',', '.')
        else:
            # Si sólo tiene ',', asúmela como decimal
            if ',' in s:
                s = s.replace('.', '')  # por si acaso vinieran puntos de miles mezclados
                s = s.replace(',', '.')
            else:
                # Sólo tiene puntos. ¿Es decimal?
                parts = s.split('.')
                if len(parts) > 1 and len(parts[-1]) <= 2:
                    # ej: 146004.84 => decimal, se conserva
                    s = ''.join(parts[:-1]) + '.' + parts[-1]
                else:
                    # ej: 1.234.567 => miles, se remueven
                    s = s.replace('.', '')

        try:
            return Decimal(s)
        except InvalidOperation:
            return Decimal(0)

    def _format_colombian(self, num_str):
        """Formatea a miles con punto. Acepta str/Decimal/float; sin decimales en la salida."""
        try:
            val = self._parse_number(num_str)
            return f"{int(val):,}".replace(",", ".")
        except Exception:
            return str(num_str)

    def _draw_wrapped_text(self, p, x, y, text, max_width=35):
        """Escribe texto con salto de línea si excede longitud."""
        if not text:
            return y
        lines = textwrap.wrap(text, width=max_width)
        for i, line in enumerate(lines):
            p.drawString(x, y - (i * 12), line)
        return y - (len(lines) - 1) * 12

    def _draw_header(self, p, width, height):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'Logo.png')
        p.drawImage(logo_path, 40, height - 50, width=140, height=55,
                    preserveAspectRatio=True, anchor='w', mask='auto')
        p.setFont("Helvetica-Bold", 18)
        p.drawCentredString(width / 2.0, height - 40, "LIQUIDACIÓN DE CRÉDITO")

    def _draw_client_data(self, p, width, y_start, flujo_data):
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 70, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Datos del cliente")
        
        y = y_start - 15
        line_height = 22
        col_1_label = 50
        col_1_value = 160
        col_2_label = 320
        col_2_value = 430
        
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Identificación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('CEDULA', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Nombre:")
        p.setFont("Helvetica", 9.5)
        y = self._draw_wrapped_text(p, col_2_value, y, flujo_data.get('NOMBRE', 'N/A'), max_width=35)

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Fecha expedición:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FECHAEXPEDICION', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Lugar expedición:")
        p.setFont("Helvetica", 9.5)
        # p.drawString(col_2_value, y, flujo_data.get('LUGAREXP', 'N/A'))
        y = self._draw_wrapped_text(p, col_2_value, y, flujo_data.get('LUGAREXP', ''), max_width=35) #! SE UTILIZA UNA FUNCIÓN PARA HACER WRAP

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Código:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('CODIGO', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Dirección:")
        p.setFont("Helvetica", 9.5)
        # p.drawString(col_2_value, y, flujo_data.get('DIRECCION', ''))
        y = self._draw_wrapped_text(p, col_2_value, y, flujo_data.get('DIRECCION', ''), max_width=35) #! SE UTILIZA UNA FUNCIÓN PARA HACER WRAP

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Ciudad:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('CIUDADRES', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Departamento:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('DPTORES', ''))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Dependencia:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('DEPENDENCIA', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Ubicación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('UBICACION', ''))
        
        return y - 25

    def _draw_obligation_data(self, p, width, y_start, flujo_data):
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 70, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Datos de la obligación")
        
        # SUBE ligeramente la primera línea (antes: y_start - 25)
        y = y_start - 18
        line_height = 15
        col_1_label = 50
        col_1_value = 160
        col_2_label = 320
        col_2_value = 430

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Solicitud:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('SOLICITUD', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Obligación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('OBLIGACION', 'N/A'))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Número del pagaré:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('PAGARE', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Modalidad:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('MODALIDAD', ''))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Destinación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('DESTINACION', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Medio de pago:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('MEDIOPAGO', ''))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Linea:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('LINEA', ''))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Fecha de solicitud:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('FECHASOL', 'N/A'))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Fecha de aprobación:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FECHAAPRO', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Fecha de desembolso:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('FECHADESE', 'N/A'))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "T.E.A:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('TEA', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "T.N.A.M.V:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('TNAM', 'N/A'))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Tasa Periódica:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('TASAPERIODO', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Tasa de usura:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('TASAUSURA', 'N/A'))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Otros conceptos:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('OTROSCONCEPTO', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Tipo de tasa:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('TIPOTASA', 'Fija'))

        y -= line_height

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Factor de variabilidad:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FACVARIABI', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Forma de pago:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('FORMAPAGO', ''))


        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Fecha primera cuota:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, flujo_data.get('FECHAPRIMERA', 'N/A'))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Fecha última cuota:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('FECHAULTIMA', 'N/A'))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Número de cuotas:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, str(flujo_data.get('NUMEROCUOTAS', 'N/A')))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Valor de la cuota:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, self._format_colombian(flujo_data.get('VALORCUOTA', 'N/A')))

        y -= line_height
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_1_label, y, "Día de vencimiento:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_1_value, y, str(flujo_data.get('DIAVENCIMIENTO', 'N/A')))

        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(col_2_label, y, "Periodicidad de pago:")
        p.setFont("Helvetica", 9.5)
        p.drawString(col_2_value, y, flujo_data.get('PERIODOPAGO', 'Mensual'))

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
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 70, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Detalle de liquidación")
        
        y_pos = y_start - 2

        liquidacion_data = [
            {'concepto': 'Monto', 'obligacion': self._format_colombian(flujo_data.get('MONTOOBLIGA', '0')), 'debito': self._format_colombian(flujo_data.get('MONTODEBITO', '0')), 'credito': self._format_colombian(flujo_data.get('MONTOCREDITO', '0'))},
            {'concepto': 'Intereses Anticipados de Ajuste al ciclo', 'obligacion': self._format_colombian(flujo_data.get('INTEOBLIGA', '0')), 'debito': self._format_colombian(flujo_data.get('INTEDEBITO', '0')), 'credito': self._format_colombian(flujo_data.get('INTECREDITO', '0'))},
            {'concepto': 'Obligaciones de cartera financiera que recoge', 'obligacion': self._format_colombian(flujo_data.get('OBLIOBLIGA', '0')), 'debito': self._format_colombian(flujo_data.get('OBLIDEBITO', '0')), 'credito': self._format_colombian(flujo_data.get('OBLICREDITO', '0'))},
            {'concepto': 'Obligaciones 2', 'obligacion': self._format_colombian(flujo_data.get('OBLI2OBLIGA', '0')), 'debito': self._format_colombian(flujo_data.get('OBLI2DEBITO', '0')), 'credito': self._format_colombian(flujo_data.get('OBLI2CREDITO', '0'))},
            {'concepto': 'Neto a Girar', 'obligacion': self._format_colombian(flujo_data.get('NETOOBLIGA', '0')), 'debito': self._format_colombian(flujo_data.get('NETODEBITO', '0')), 'credito': self._format_colombian(flujo_data.get('NETOCREDITO', '0'))}
        ]
        
        table_data = [['Concepto', 'Obligación', 'Débito', 'Crédito']]
        
        for item in liquidacion_data:
            table_data.append([item.get('concepto', ''), item.get('obligacion', ''), item.get('debito', ''), item.get('credito', '')])
        
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

    def _draw_guarantees_data(self, p, width, y_start, flujo_data):
        """Dibuja la sección de Garantías con estructura 2x2:
        Aportes (ancho completo), y debajo Personales / Reales en columnas."""
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 70, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_start + 7, "Garantías")

        # Margen superior más pegado al título
        y = y_start - 14
        left = 50
        wrap_w_full = 90   # ancho de línea para Aportes
        wrap_w_col = 45    # ancho para columnas Personales / Reales
        col_gap = 270      # distancia horizontal entre columnas

        # ------------------------------------------------------------------
        # APORTES (una sola fila, ocupa todo el ancho)
        # ------------------------------------------------------------------
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(left, y, "Aportes")
        y -= 12
        p.setFont("Helvetica", 9)
        aportes_val = flujo_data.get('GARANAPOPIGNO', '') or 'PIGNORACIÓN: NO HA PIGNORADO APORTES'
        for line in textwrap.wrap(aportes_val, width=wrap_w_full):
            p.drawString(left + 10, y, line)
            y -= 11

        # Espacio pequeño entre Aportes y el bloque inferior
        y -= 5
        y_bottom_start = y

        # ------------------------------------------------------------------
        # PERSONALES (columna izquierda)
        # ------------------------------------------------------------------
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(left, y_bottom_start, "Personales")
        y_left = y_bottom_start - 12
        p.setFont("Helvetica-Bold", 9)
        p.drawString(left + 10, y_left, "Nombre")
        y_left -= 12
        p.setFont("Helvetica", 9)
        personales_val = flujo_data.get('PERSONAL', '') or 'SIN CODEUDORES'
        personales_list = [s.strip() for s in personales_val.split(';') if s.strip()] or [personales_val]
        for item in personales_list:
            for line in textwrap.wrap(item, width=wrap_w_col):
                p.drawString(left + 10, y_left, f"• {line}")
                y_left -= 11

        # ------------------------------------------------------------------
        # REALES (columna derecha)
        # ------------------------------------------------------------------
        right = left + col_gap
        p.setFont("Helvetica-Bold", 9.5)
        p.drawString(right, y_bottom_start, "Reales")
        y_right = y_bottom_start - 12
        p.setFont("Helvetica-Bold", 9)
        p.drawString(right + 10, y_right, "Descripción")
        y_right -= 12
        p.setFont("Helvetica", 9)
        reales_val = (
            flujo_data.get('REALDESCRIPCION')
            or flujo_data.get('REALDESCRIPCIO')
            or 'FGA GARANTÍA: SIN DETALLE'
        )
        reales_list = [s.strip() for s in reales_val.split(';') if s.strip()] or [reales_val]
        for item in reales_list:
            for line in textwrap.wrap(item, width=wrap_w_col):
                p.drawString(right + 10, y_right, f"• {line}")
                y_right -= 11

        # ------------------------------------------------------------------
        # Ajusta retorno para continuar el flujo del documento
        # ------------------------------------------------------------------
        return min(y_left, y_right) - 20


    def _draw_payment_table(self, p, width, y_start, flujo_data, start_row=0, end_row=None):
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_start, width - 70, 22, fill=1, stroke=0)
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

        headers = ["No.", "Fecha", "Abono\nCapital", "Abono\nInterés", "Seguro de\nvida", "Otros\nconceptos", "Capitalización", "Valor Cuota", "Saldo\nparcial"]
        col_names = ['NO', 'FECHA', 'ABONO_CAPITAL', 'ABONO_INTERES', 'SEGURO_VIDA', 'OTROS_CONCEPTOS', 'CAPITALIZACION', 'VALOR_CUOTA', 'SALDO_PARCIAL']
        
        table_data = [headers]
        
        for row in data_slice:
            formatted_row = []
            for idx, col_name in enumerate(col_names):
                value = row.get(col_name, '')
                if idx > 1:
                    formatted_row.append(self._format_colombian(value))
                else:
                    formatted_row.append(str(value))
            table_data.append(formatted_row)

        is_last_slice = (end_row >= len(plan_pago_data))
        # Dentro de _draw_payment_table, en el bloque de totales:
        if is_last_slice and len(plan_pago_data) > 0:
            totales = ['Totales', '']
            for col_idx, col_name in enumerate(col_names):
                if col_idx > 1:
                    total = sum(self._parse_number(row.get(col_name, 0)) for row in plan_pago_data if row.get(col_name) not in (None, ''))
                    totales.append(self._format_colombian(total))
            # Vacía el total de "Saldo parcial"
            totales[-1] = ''
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
        if y_position < 100:
            p.showPage()
            y_position = 750
        
        p.setFillColor(HexColor('#d9d9d9'))
        p.rect(40, y_position, width - 70, 22, fill=1, stroke=0)
        p.setFillColor(HexColor('#000000'))
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y_position + 7, "Firmas")
        
        y = y_position - 40
        p.setFont("Helvetica-Bold", 9.5)
        p.line(50, y, 250, y)
        p.drawString(50, y - 12, "Nombre del deudor")
        
        p.line(350, y, 550, y)
        p.drawString(350, y - 12, "Firma")

    def _draw_page_number(self, p, width, height, page_num):
        p.setFont("Helvetica", 9.5)
        p.drawRightString(width - 40, 30, f"Página: {page_num}")

    def get(self, request, cedula):
        try:
            flujos_filtrados = _filtrar_flujos(cedula=cedula)
            
            if not flujos_filtrados:
                return JsonResponse({"error": "Flujo no encontrado para la cédula proporcionada"}, status=status.HTTP_404_NOT_FOUND)

            target_flujo = flujos_filtrados[0]

            buffer = io.BytesIO()
            p = canvas.Canvas(buffer, pagesize=letter)
            width, height = letter
            
            self._draw_header(p, width, height)
            
            y_pos = height - 80
            y_pos = self._draw_client_data(p, width, y_pos, target_flujo)
            y_pos -= 4
            y_pos = self._draw_obligation_data(p, width, y_pos, target_flujo)
            y_pos -= 4
            y_pos = self._draw_liquidation_detail(p, width, y_pos, target_flujo)
            y_pos -= 6
            y_pos = self._draw_guarantees_data(p, width, y_pos, target_flujo)
            
            plan_pago_data = target_flujo.get('PLAN_PAGO', [])
            rows_per_page = 30
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

            self._draw_footer(p, width, y_pos_after_table - 25)
            
            p.save()
            buffer.seek(0)

            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="plan_pago_{cedula}_{datetime.now().strftime("%Y%m%d")}.pdf"'
            return response

        except Exception as e:
            logger.error(f"Error en GenerarPDF para cedula {cedula}: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
