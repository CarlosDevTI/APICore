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
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from itertools import groupby
from operator import itemgetter

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
        responses={
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
                {"CEDULA": flow.get("CEDULA"), "NOMBRE": flow.get("NOMBRE"), "MAIL": flow.get("MAIL")}
                for flow in all_flows
            ]
            return JsonResponse(summary_list, safe=False, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error en la función ListarFlujosPendientes: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PDFTemplate(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        self.page_count = 0
        self.addPageTemplates([
            PageTemplate(
                id='main',
                frames=[Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id='normal')],
                onPage=self.header,
                onPageEnd=self.footer
            )
        ])

    def header(self, canvas, doc):
        canvas.saveState()
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'Logo.png')
        canvas.drawImage(logo_path, 40, doc.height + self.topMargin - 50, width=120, height=50, preserveAspectRatio=True, anchor='w', mask='auto')
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawCentredString(doc.width / 2.0 + doc.leftMargin, doc.height + self.topMargin - 40, "LIQUIDACIÓN DE CRÉDITO")
        canvas.restoreState()

    def footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9.5)
        page_num = canvas.getPageNumber()
        if hasattr(doc, 'total_pages'):
            canvas.drawRightString(doc.width + doc.leftMargin, 30, f"Página: {page_num}/{doc.total_pages}")
        canvas.restoreState()

class GenerarPDF(APIView):
    def _format_number(self, value):
        try:
            number = float(str(value).replace('.', '').replace(',', '.'))
            formatted_value = f'{number:,.0f}'
            return formatted_value.replace(',', '.')
        except (ValueError, TypeError):
            return value

    def _get_section_title(self, title, style):
        return Paragraph(title, style)

    def _get_client_data_table(self, flujo_data, styles):
        style = styles['Normal']
        style.fontName = 'Helvetica'
        style.fontSize = 9.5
        style.leading = 12

        def create_para(text, bold=False):
            return Paragraph(f'<b>{text}</b>' if bold else str(text), style)

        data = [
            [create_para("Identificación:", True), create_para(flujo_data.get('CEDULA', '')),
             create_para("Nombre:", True), create_para(flujo_data.get('NOMBRE', ''))],
            [create_para("Fecha expedición:", True), create_para(flujo_data.get('FECHA_EXPEDICION', 'N/A')),
             create_para("Lugar expedición:", True), create_para(flujo_data.get('LUGAR_EXPEDICION', 'N/A'))],
            [create_para("Código:", True), create_para(flujo_data.get('CODIGO', '')),
             create_para("Dirección:", True), create_para(flujo_data.get('DIRECCION', ''))],
            [create_para("Ciudad:", True), create_para(flujo_data.get('CIUDAD', '')),
             create_para("Departamento:", True), create_para(flujo_data.get('DEPARTAMENTO', ''))],
            [' ', '', '', ''],
            [create_para("Dependencia:", True), create_para(flujo_data.get('DEPENDENCIA', '')),
             create_para("Ubicación:", True), create_para(flujo_data.get('UBICACION', ''))]
        ]
        table = Table(data, colWidths=[110, 160, 110, 152])
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('SPAN', (0, 4), (-1, 4)),
            ('BOTTOMPADDING', (0, 3), (-1, 3), 10),
        ]))
        return table

    def _get_obligation_data_table(self, flujo_data, styles):
        style = styles['Normal']
        style.fontName = 'Helvetica'
        style.fontSize = 9.5
        style.leading = 12

        def create_para(text, bold=False):
            return Paragraph(f'<b>{text}</b>' if bold else str(text), style)

        data = [
            [create_para("Solicitud:", True), create_para(flujo_data.get('SOLICITUD', 'N/A')), create_para("Obligación:", True), create_para(flujo_data.get('OBLIGACION', 'N/A'))],
            [create_para("Número del pagaré:", True), create_para(flujo_data.get('NUM_PAGARE', 'N/A')), create_para("Modalidad:", True), create_para(flujo_data.get('MODALIDAD', ''))],
            [create_para("Destinación:", True), create_para(flujo_data.get('DESTINACION', 'N/A')), create_para("Medio de pago:", True), create_para(flujo_data.get('MEDIO_PAGO', ''))],
            [create_para("Linea:", True), create_para(flujo_data.get('LINEA', '')), create_para("Fecha de solicitud:", True), create_para(flujo_data.get('FECHA_SOLICITUD', 'N/A'))],
            [create_para("Fecha de aprobación:", True), create_para(flujo_data.get('FECHA_APROBACION', 'N/A')), create_para("Fecha de desembolso:", True), create_para(flujo_data.get('FECHA_DESEMBOLSO', 'N/A'))],
            [create_para("T.E.A:", True), create_para(flujo_data.get('TEA', 'N/A')), create_para("T.N.A.M.V:", True), create_para(flujo_data.get('TNAMV', 'N/A'))],
            [create_para("Tasa Periódica:", True), create_para(flujo_data.get('TASA_PERIODICA', 'N/A')), create_para("Tasa de usura:", True), create_para(flujo_data.get('TASA_USURA', 'N/A'))],
            [create_para("Otros conceptos:", True), create_para(flujo_data.get('OTROS_CONCEPTOS_INFO', 'N/A')), create_para("Seg. Vida:", True), create_para(flujo_data.get('SEG_VIDA_PERCENT', 'N/A'))],
            [create_para("Forma de pago:", True), create_para(flujo_data.get('FORMA_PAGO', '')), create_para("Tipo de tasa:", True), create_para(flujo_data.get('TIPO_TASA', 'Fija'))],
            [create_para("Fecha primera cuota:", True), create_para(flujo_data.get('FECHA_PRIMERA_CUOTA', 'N/A')), create_para("Fecha última cuota:", True), create_para(flujo_data.get('FECHA_ULTIMA_CUOTA', 'N/A'))],
            [create_para("Número de cuotas:", True), create_para(str(flujo_data.get('NUM_CUOTAS', 'N/A'))), create_para("Valor de la cuota:", True), create_para(self._format_number(flujo_data.get('VALORCUOTA', 'N/A')))],
            [create_para("Día de vencimiento:", True), create_para(str(flujo_data.get('DIA_VENCIMIENTO', 'N/A'))), create_para("Periodicidad de pago:", True), create_para(flujo_data.get('PERIODICIDAD', 'Mensual'))],
            [create_para("Garantía:", True), create_para(flujo_data.get('GARANTIA', 'N/A')), create_para("Clasificación:", True), create_para(flujo_data.get('CLASIFICACION', 'Consumo'))],
        ]
        table = Table(data, colWidths=[110, 160, 110, 152])
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
        ]))
        return table

    def _get_liquidation_detail_table(self, flujo_data, styles):
        data = [
            ['Concepto', 'Obligación', 'Débito', 'Crédito'],
            ['Monto', self._format_number(flujo_data.get('MONTO', '0')), self._format_number('0'), ''],
            ['Intereses Anticipados de Ajuste al ciclo', '', self._format_number('0'), self._format_number(flujo_data.get('INT_ANTICIPADOS', '0'))],
            ['Obligaciones de cartera financiera que recoge', flujo_data.get('OBLIG_RECOGE', ''), self._format_number('0'), self._format_number(flujo_data.get('OBLIG_RECOGE_VALOR', '0'))],
            ['Neto a Girar', '', self._format_number('0'), self._format_number(flujo_data.get('NETO_GIRAR', '0'))]
        ]
        table = Table(data, colWidths=[280, 100, 80, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#d9d9d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9.5),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        return table

    def _get_payment_table(self, flujo_data, styles):
        plan_pago_data = flujo_data.get('PLAN_PAGO', [])
        if not plan_pago_data:
            return Paragraph("No hay datos del plan de pago disponibles.", styles['Normal'])

        headers = ["No.", "Fecha", "Abono\nCapital", "Abono\nInterés", "Seguro de\nvida", "Otros\nconceptos", "Capitalización", "Valor Cuota", "Saldo\nparcial"]
        col_names = ['CUOTA', 'FECHA', 'ABONO_CAPITAL', 'ABONO_INTERES', 'SEGURO_VIDA', 'OTROS_CONCEPTOS', 'CAPITALIZACION', 'VALOR_CUOTA', 'SALDO_PARCIAL']
        table_data = [headers]

        for row in plan_pago_data:
            table_data.append([self._format_number(row.get(col, '')) if col not in ['CUOTA', 'FECHA'] else row.get(col, '') for col in col_names])

        if len(table_data) > 1:
            totales = ['Totales', '']
            for col_idx, col_name in enumerate(col_names):
                if col_idx > 1:
                    try:
                        total = sum(float(str(row.get(col_name, 0)).replace(',', '')) for row in plan_pago_data if row.get(col_name))
                        totales.append(self._format_number(total))
                    except (ValueError, TypeError):
                        totales.append('0')
            totales[-1] = ''
            table_data.append(totales)

        table = Table(table_data, colWidths=[30, 60, 60, 60, 55, 55, 60, 60, 70])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#d9d9d9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8.5),
            ('BACKGROUND', (0, -1), (-1, -1), HexColor('#f0f0f0')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        return table

    def _get_footer_table(self, styles):
        style = styles['Normal'].clone('footer_style')
        style.fontName = 'Helvetica-Bold'
        style.fontSize = 9.5
        style.alignment = 1 # Center alignment

        data = [
            [Paragraph("_", style), Paragraph("_", style)],
            [Paragraph("Nombre del deudor", style), Paragraph("Firma", style)]
        ]
        table = Table(data, colWidths=[250, 250])
        table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 20), # Space for signature line
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ]))
        return table

    @swagger_auto_schema(
        operation_description="""Genera un PDF para un único flujo de plan de pagos especificado por su ID.""",
        manual_parameters=[
            openapi.Parameter('cedula', openapi.IN_PATH, description="Cédula del cliente a generar.", type=openapi.TYPE_STRING, required=True)
        ],
        responses={ 
            200: openapi.Response('PDF del plan de pagos generado exitosamente.', schema=openapi.Schema(type=openapi.TYPE_FILE)),
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
            doc = PDFTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=80, bottomMargin=50)
            
            styles = getSampleStyleSheet()
            title_style = styles['h2'].clone('title_style')
            title_style.fontName = 'Helvetica-Bold'
            title_style.fontSize = 10
            title_style.textColor = colors.black
            title_style.backColor = HexColor('#d9d9d9')
            title_style.leading = 16
            title_style.leftIndent = -6
            title_style.rightIndent = -6

            story = []
            story.append(self._get_section_title("Datos del cliente", title_style))
            story.append(self._get_client_data_table(target_flujo, styles))
            story.append(Spacer(1, 0.2 * inch))
            story.append(self._get_section_title("Datos de la obligación", title_style))
            story.append(self._get_obligation_data_table(target_flujo, styles))
            story.append(Spacer(1, 0.2 * inch))
            story.append(self._get_section_title("Detalle de liquidación", title_style))
            story.append(self._get_liquidation_detail_table(target_flujo, styles))
            story.append(Spacer(1, 0.2 * inch))
            story.append(self._get_section_title("Ciclo de pago", title_style))
            story.append(self._get_payment_table(target_flujo, styles))
            story.append(Spacer(1, 0.4 * inch))
            story.append(self._get_section_title("Firmas", title_style))
            story.append(self._get_footer_table(styles))

            def count_pages(canvas, doc):
                canvas.page_count = canvas.getPageNumber()

            doc.multiBuild(story, onEndFirstPass=count_pages)

            doc.total_pages = doc.canv.page_count
            doc.multiBuild(story)

            buffer.seek(0)
            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="plan_pago_{cedula}_{datetime.now().strftime("%Y%m%d")}.pdf"'
            return response

        except Exception as e:
            logger.error(f"Error en GenerarPDF para cedula {cedula}: {e}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
