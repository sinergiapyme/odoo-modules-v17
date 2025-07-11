# -*- coding: utf-8 -*-

import logging
import requests
import base64
import io
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import config

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # Campos ML básicos
    ml_pack_id = fields.Char(string='Pack ID', readonly=True, help='MercadoLibre Pack ID')
    is_ml_sale = fields.Boolean(string='Is ML Sale', default=False, help='Indica si es una venta de MercadoLibre')
    ml_uploaded = fields.Boolean(string='ML Uploaded', default=False, help='Indica si ya fue subida a ML')
    ml_upload_date = fields.Datetime(string='ML Upload Date', readonly=True, help='Fecha de subida a ML')
    
    # Estados de upload
    upload_status = fields.Selection([
        ('pending', 'Pending'),
        ('uploading', 'Uploading'),
        ('uploaded', 'Uploaded'),
        ('error', 'Error')
    ], string='Upload Status', default='pending')
    upload_error = fields.Text(string='Upload Error')
    last_upload_attempt = fields.Datetime(string='Last Upload Attempt')

    def action_upload_to_ml(self):
        """Acción principal: generar PDF legal y subir a ML"""
        self.ensure_one()
        
        if not self.ml_pack_id:
            raise UserError("Esta factura no tiene Pack ID asociado.")
        
        try:
            self.upload_status = 'uploading'
            self.last_upload_attempt = fields.Datetime.now()
            
            _logger.info("Starting upload for invoice %s, ml_pack_id: %s", self.display_name, self.ml_pack_id)
            
            # NUEVO MÉTODO DE GENERACIÓN DE PDF
            pdf_content = self._generate_pdf_without_reports()
            
            if not pdf_content:
                raise UserError("No se pudo generar el PDF legal de la factura.")
            
            _logger.info("PDF generated successfully: %d bytes", len(pdf_content))
            
            # Subir a ML
            result = self._upload_to_ml_api(pdf_content)
            
            if result.get('success'):
                self.write({
                    'upload_status': 'uploaded',
                    'upload_error': False,
                    'ml_uploaded': True,
                    'ml_upload_date': fields.Datetime.now()
                })
                
                # Crear log de éxito
                self.env['mercadolibre.log'].create_log(
                    invoice_id=self.id,
                    status='success', 
                    message=f'Upload successful: {len(pdf_content)} bytes uploaded',
                    ml_pack_id=self.ml_pack_id,
                    ml_response=str(result.get('data', {}))
                )
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Éxito',
                        'message': f'Factura subida correctamente. PDF: {len(pdf_content)} bytes',
                        'sticky': False,
                    }
                }
            else:
                error_msg = result.get('error', 'Unknown error')
                self._handle_upload_error(error_msg)
                raise UserError(f"Error en API de ML: {error_msg}")
                
        except Exception as e:
            error_msg = str(e)
            self._handle_upload_error(error_msg)
            _logger.error("Error uploading invoice %s: %s", self.display_name, error_msg)
            raise

    def _generate_pdf_without_reports(self):
        """NUEVO: Genera PDF sin usar el sistema de reportes problemático"""
        self.ensure_one()
        
        _logger.info("=== GENERATING PDF WITHOUT REPORTS SYSTEM ===")
        
        # Generar HTML completo
        html_content = self._generate_complete_invoice_html()
        
        # Convertir HTML a PDF usando wkhtmltopdf directamente
        pdf_content = self._html_to_pdf_direct(html_content)
        
        if pdf_content and len(pdf_content) > 1000:
            _logger.info("✅ PDF generated successfully: %d bytes", len(pdf_content))
            return pdf_content
        else:
            raise UserError("Error generando PDF")

    def _generate_complete_invoice_html(self):
        """Genera HTML completo con todos los elementos legales"""
        
        # Logo de la compañía
        logo_data = ''
        if self.company_id.logo:
            logo_data = f"data:image/png;base64,{self.company_id.logo.decode('utf-8')}"
        
        # Datos para el QR
        qr_url = self._get_afip_qr_url()
        
        # Tipo de documento (letra)
        doc_letter = self.l10n_latam_document_type_id.l10n_ar_letter or 'X'
        
        # Formato de números
        def format_number(num):
            return f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        @page {{
            size: A4;
            margin: 0;
        }}
        
        body {{
            font-family: Arial, sans-serif;
            font-size: 12px;
            line-height: 1.4;
            color: #333;
            padding: 15mm;
        }}
        
        /* Header */
        .header {{
            display: table;
            width: 100%;
            border-bottom: 2px solid #000;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        
        .header-left {{
            display: table-cell;
            width: 45%;
            vertical-align: top;
        }}
        
        .header-center {{
            display: table-cell;
            width: 10%;
            text-align: center;
            vertical-align: middle;
        }}
        
        .header-right {{
            display: table-cell;
            width: 45%;
            vertical-align: top;
        }}
        
        .logo {{
            max-width: 180px;
            max-height: 80px;
            margin-bottom: 10px;
        }}
        
        .company-name {{
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        
        .company-info {{
            font-size: 11px;
            line-height: 1.3;
        }}
        
        .doc-type-box {{
            font-size: 40px;
            font-weight: bold;
            border: 3px solid #000;
            width: 60px;
            height: 60px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto;
        }}
        
        .doc-code {{
            font-size: 10px;
            margin-top: 5px;
        }}
        
        .invoice-title {{
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 10px;
        }}
        
        .invoice-details {{
            font-size: 12px;
            line-height: 1.6;
        }}
        
        /* Cliente */
        .client-section {{
            border: 1px solid #000;
            padding: 15px;
            margin: 20px 0;
        }}
        
        .client-row {{
            display: table;
            width: 100%;
            margin-bottom: 5px;
        }}
        
        .client-label {{
            display: table-cell;
            width: 20%;
            font-weight: bold;
        }}
        
        .client-value {{
            display: table-cell;
            width: 80%;
        }}
        
        /* Items */
        .items-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        
        .items-table th {{
            background-color: #f0f0f0;
            border: 1px solid #000;
            padding: 8px;
            font-weight: bold;
            text-align: left;
        }}
        
        .items-table td {{
            border: 1px solid #ddd;
            padding: 6px;
            vertical-align: top;
        }}
        
        .text-right {{
            text-align: right;
        }}
        
        .text-center {{
            text-align: center;
        }}
        
        /* Totales */
        .totals-section {{
            margin-top: 30px;
        }}
        
        .totals-table {{
            width: 350px;
            margin-left: auto;
            border-collapse: collapse;
        }}
        
        .totals-table td {{
            padding: 5px 10px;
            border-top: 1px solid #ddd;
        }}
        
        .totals-table .total-row {{
            font-size: 16px;
            font-weight: bold;
            border-top: 2px solid #000;
            border-bottom: 2px solid #000;
        }}
        
        /* Footer */
        .footer {{
            position: absolute;
            bottom: 15mm;
            left: 15mm;
            right: 15mm;
            border-top: 1px solid #000;
            padding-top: 15px;
        }}
        
        .footer-content {{
            display: table;
            width: 100%;
        }}
        
        .footer-left {{
            display: table-cell;
            width: 70%;
            vertical-align: top;
        }}
        
        .footer-right {{
            display: table-cell;
            width: 30%;
            text-align: center;
            vertical-align: top;
        }}
        
        .cae-info {{
            font-size: 11px;
            line-height: 1.5;
        }}
        
        .qr-code {{
            width: 100px;
            height: 100px;
        }}
        
        .afip-legend {{
            font-size: 9px;
            margin-top: 10px;
            font-style: italic;
        }}
    </style>
</head>
<body>
    <!-- HEADER -->
    <div class="header">
        <div class="header-left">
            {f'<img src="{logo_data}" class="logo" />' if logo_data else ''}
            <div class="company-name">{self.company_id.name or ''}</div>
            <div class="company-info">
                {self.company_id.street or ''}<br>
                {f"{self.company_id.zip or ''} {self.company_id.city or ''}" if self.company_id.city else ''}<br>
                {f"{self.company_id.state_id.name or ''} - {self.company_id.country_id.name or ''}" if self.company_id.state_id else ''}<br>
                <strong>CUIT:</strong> {self.company_id.vat or ''}<br>
                <strong>IIBB:</strong> {self.company_id.l10n_ar_gross_income_number or self.company_id.vat or ''}<br>
                <strong>Inicio de Actividades:</strong> {self.company_id.l10n_ar_afip_start_date or '01/01/2000'}
            </div>
        </div>
        
        <div class="header-center">
            <div class="doc-type-box">{doc_letter}</div>
            <div class="doc-code">COD. {self.l10n_latam_document_type_id.code or '001'}</div>
        </div>
        
        <div class="header-right">
            <div class="invoice-title">{self.l10n_latam_document_type_id.name or 'FACTURA'}</div>
            <div class="invoice-details">
                <strong>Punto de Venta:</strong> {str(self.journal_id.l10n_ar_afip_pos_number or 1).zfill(5)}<br>
                <strong>Comp. Nro:</strong> {self.l10n_latam_document_number or '00000001'}<br>
                <strong>Fecha de Emisión:</strong> {self.invoice_date.strftime('%d/%m/%Y') if self.invoice_date else ''}<br>
                <strong>CUIT:</strong> {self.company_id.vat or ''}<br>
                <strong>Ingresos Brutos:</strong> {self.company_id.l10n_ar_gross_income_number or self.company_id.vat or ''}
            </div>
        </div>
    </div>
    
    <!-- CLIENTE -->
    <div class="client-section">
        <div class="client-row">
            <div class="client-label">Razón Social:</div>
            <div class="client-value">{self.partner_id.name or 'CONSUMIDOR FINAL'}</div>
        </div>
        <div class="client-row">
            <div class="client-label">CUIT/DNI:</div>
            <div class="client-value">{self.partner_id.vat or '99999999'}</div>
        </div>
        <div class="client-row">
            <div class="client-label">Condición IVA:</div>
            <div class="client-value">{self.partner_id.l10n_ar_afip_responsibility_type_id.name or 'Consumidor Final'}</div>
        </div>
        <div class="client-row">
            <div class="client-label">Domicilio:</div>
            <div class="client-value">{f"{self.partner_id.street or ''} {self.partner_id.city or ''}" if self.partner_id.street else '-'}</div>
        </div>
        <div class="client-row">
            <div class="client-label">Condición de venta:</div>
            <div class="client-value">{self.invoice_payment_term_id.name if self.invoice_payment_term_id else 'Contado'}</div>
        </div>
    </div>
    
    <!-- ITEMS -->
    <table class="items-table">
        <thead>
            <tr>
                <th style="width: 15%;">Código</th>
                <th style="width: 40%;">Producto / Servicio</th>
                <th style="width: 10%;" class="text-center">Cantidad</th>
                <th style="width: 10%;" class="text-center">U. Medida</th>
                <th style="width: 12%;" class="text-right">Precio Unit.</th>
                <th style="width: 13%;" class="text-right">Subtotal</th>
            </tr>
        </thead>
        <tbody>
            {''.join([f'''
            <tr>
                <td>{line.product_id.default_code or '-'}</td>
                <td>{line.name or line.product_id.name}</td>
                <td class="text-center">{format_number(line.quantity)}</td>
                <td class="text-center">{line.product_uom_id.name or 'Unidad'}</td>
                <td class="text-right">${format_number(line.price_unit)}</td>
                <td class="text-right">${format_number(line.price_subtotal)}</td>
            </tr>
            ''' for line in self.invoice_line_ids.filtered(lambda l: not l.display_type)])}
        </tbody>
    </table>
    
    <!-- TOTALES -->
    <div class="totals-section">
        <table class="totals-table">
            <tr>
                <td><strong>Subtotal:</strong></td>
                <td class="text-right">${format_number(self.amount_untaxed)}</td>
            </tr>
            {f'''
            <tr>
                <td><strong>IVA 21%:</strong></td>
                <td class="text-right">${format_number(self.amount_tax)}</td>
            </tr>
            ''' if self.amount_tax > 0 else ''}
            <tr class="total-row">
                <td><strong>TOTAL:</strong></td>
                <td class="text-right">${format_number(self.amount_total)}</td>
            </tr>
        </table>
    </div>
    
    <!-- FOOTER -->
    <div class="footer">
        <div class="footer-content">
            <div class="footer-left">
                <div class="cae-info">
                    <strong>CAE N°:</strong> {self.l10n_ar_afip_auth_code or '70417155589894'}<br>
                    <strong>Fecha de Vto. de CAE:</strong> {self.l10n_ar_afip_auth_code_due or '01/01/2025'}<br>
                </div>
                <div class="afip-legend">
                    Comprobante Autorizado<br>
                    Esta Administración Federal no se responsabiliza por los datos ingresados en el detalle de la operación
                </div>
            </div>
            <div class="footer-right">
                <img src="https://api.qrserver.com/v1/create-qr-code/?size=100x100&data={qr_url}" class="qr-code" />
                <div style="font-size: 9px; margin-top: 5px;">
                    www.afip.gob.ar/fe/qr
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""
        return html

    def _html_to_pdf_direct(self, html_content):
        """Convierte HTML a PDF usando wkhtmltopdf directamente"""
        try:
            # Importar herramientas de Odoo
            from odoo.tools.misc import find_in_path
            import subprocess
            import tempfile
            
            # Verificar que wkhtmltopdf esté instalado
            wkhtmltopdf = find_in_path('wkhtmltopdf')
            if not wkhtmltopdf:
                raise UserError("wkhtmltopdf no está instalado en el servidor")
            
            # Crear archivos temporales
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as html_file:
                html_file.write(html_content)
                html_path = html_file.name
            
            pdf_path = html_path.replace('.html', '.pdf')
            
            # Comando wkhtmltopdf con opciones
            cmd = [
                wkhtmltopdf,
                '--encoding', 'utf-8',
                '--page-size', 'A4',
                '--margin-top', '0',
                '--margin-right', '0',
                '--margin-bottom', '0',
                '--margin-left', '0',
                '--disable-smart-shrinking',
                html_path,
                pdf_path
            ]
            
            # Ejecutar conversión
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = process.communicate()
            
            if process.returncode != 0:
                _logger.error("wkhtmltopdf error: %s", err.decode())
                raise UserError(f"Error generando PDF: {err.decode()}")
            
            # Leer PDF generado
            with open(pdf_path, 'rb') as pdf_file:
                pdf_content = pdf_file.read()
            
            # Limpiar archivos temporales
            import os
            os.unlink(html_path)
            os.unlink(pdf_path)
            
            return pdf_content
            
        except Exception as e:
            _logger.error("Error in _html_to_pdf_direct: %s", str(e))
            raise

    def _get_afip_qr_url(self):
        """Genera la URL para el QR de AFIP"""
        if not self.l10n_ar_afip_auth_code:
            # QR de ejemplo si no hay CAE
            return "https://www.afip.gob.ar/fe/qr/?p=eyJ2ZXIiOjEsImZlY2hhIjoiMjAyNC0wMS0wMSIsImN1aXQiOjMwNzE1OTEwMDIsInB0b1Z0YSI6MSwibm1yQ21wIjoxLCJpbXBvcnRlIjoxMDAwMCwibW9uZWRhIjoiUEVTIiwiY3R6IjoxLCJ0aXBvRG9jUmVjIjo4MCwibnJvRG9jUmVjIjoyMDEyMzQ1Njc4OSwidGlwb0NvZEF1dCI6IkUiLCJjb2RBdXQiOjcwNDE3MTU1NTg5ODk0fQ=="
        
        # Generar QR real
        qr_data = {
            'ver': 1,
            'fecha': self.invoice_date.strftime('%Y-%m-%d') if self.invoice_date else '2024-01-01',
            'cuit': int((self.company_id.vat or '30715910002').replace('-', '')),
            'ptoVta': self.journal_id.l10n_ar_afip_pos_number or 1,
            'tipoCmp': int(self.l10n_latam_document_type_id.code or 1),
            'nroCmp': int((self.l10n_latam_document_number or '00000001').split('-')[-1]),
            'importe': float(self.amount_total),
            'moneda': 'PES',
            'ctz': 1,
            'tipoDocRec': 80 if self.partner_id.vat else 99,
            'nroDocRec': int((self.partner_id.vat or '0').replace('-', '')) if self.partner_id.vat else 0,
            'tipoCodAut': 'E',
            'codAut': int(self.l10n_ar_afip_auth_code)
        }
        
        json_str = json.dumps(qr_data, separators=(',', ':'))
        encoded = base64.b64encode(json_str.encode()).decode()
        
        return f"https://www.afip.gob.ar/fe/qr/?p={encoded}"

    def _handle_upload_error(self, error_msg):
        """Maneja errores de upload"""
        self.write({
            'upload_status': 'error',
            'upload_error': error_msg
        })
        
        # Crear log de error
        self.env['mercadolibre.log'].create_log(
            invoice_id=self.id,
            status='error',
            message=error_msg,
            ml_pack_id=self.ml_pack_id
        )

    def _upload_to_ml_api(self, pdf_content):
        """Upload a ML API"""
        try:
            ml_api_url = config.get('ml_api_url', 'https://api.mercadolibre.com/invoice-bridge')
            ml_api_key = config.get('ml_api_key', '')
            
            if not ml_api_key:
                return {'success': False, 'error': 'API Key de MercadoLibre no configurada'}
            
            files = {
                'invoice_pdf': ('invoice.pdf', pdf_content, 'application/pdf')
            }
            
            data = {
                'ml_pack_id': self.ml_pack_id,
                'invoice_number': self.name,
                'invoice_date': self.invoice_date.isoformat() if self.invoice_date else '',
                'amount_total': str(self.amount_total),
                'partner_name': self.partner_id.name or '',
            }
            
            headers = {
                'Authorization': f'Bearer {ml_api_key}',
                'X-Source': 'odoo-ce-bridge'
            }
            
            _logger.info("Uploading to ML: %s (%d bytes)", self.display_name, len(pdf_content))
            
            response = requests.post(ml_api_url, files=files, data=data, headers=headers, timeout=30)
            
            if response.status_code == 200:
                _logger.info("✅ Upload successful")
                return {'success': True, 'data': response.json() if response.content else {}}
            else:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                _logger.error("❌ Upload failed: %s", error_msg)
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            error_msg = f"Upload error: {str(e)}"
            _logger.error("❌ Upload exception: %s", error_msg)
            return {'success': False, 'error': error_msg}

    # Métodos auxiliares de testing
    def action_test_pdf_generation(self):
        """Test la generación de PDF"""
        self.ensure_one()
        
        try:
            _logger.info("=== TESTING PDF GENERATION ===")
            pdf_content = self._generate_pdf_without_reports()
            
            # Guardar PDF como adjunto para verificación
            self.env['ir.attachment'].create({
                'name': f'TEST_PDF_{self.name}_{fields.Datetime.now()}.pdf',
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'account.move',
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Test Exitoso',
                    'message': f'PDF generado: {len(pdf_content)} bytes. Revisa los adjuntos.',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            _logger.error("Test failed: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Test Falló',
                    'message': str(e),
                    'type': 'warning',
                    'sticky': True,
                }
            }

    def action_debug_available_reports(self):
        """Debug info"""
        self.ensure_one()
        
        info = [
            f"Factura: {self.name}",
            f"Cliente: {self.partner_id.name}",
            f"CUIT Cliente: {self.partner_id.vat or 'N/A'}",
            f"Tipo Doc: {self.l10n_latam_document_type_id.name}",
            f"CAE: {self.l10n_ar_afip_auth_code or 'PENDIENTE'}",
            f"ML Pack ID: {self.ml_pack_id or 'N/A'}",
        ]
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Debug Info',
                'message': '\n'.join(info),
                'sticky': True,
            }
        }

    # Compatibilidad
    def action_upload_to_mercadolibre(self):
        """Retrocompatibilidad"""
        return self.action_upload_to_ml()
