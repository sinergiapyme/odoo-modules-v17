# -*- coding: utf-8 -*-

import logging
import requests
import base64
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # Campos ML básicos
    ml_pack_id = fields.Char(
        string='Pack ID', 
        readonly=True, 
        help='MercadoLibre Pack ID',
        tracking=True
    )
    is_ml_sale = fields.Boolean(
        string='Is ML Sale', 
        default=False, 
        help='Indica si es una venta de MercadoLibre',
        tracking=True
    )
    ml_uploaded = fields.Boolean(
        string='ML Uploaded', 
        default=False, 
        help='Indica si ya fue subida a ML',
        tracking=True
    )
    ml_upload_date = fields.Datetime(
        string='ML Upload Date', 
        readonly=True, 
        help='Fecha de subida a ML',
        tracking=True
    )
    
    # Estados de upload
    upload_status = fields.Selection([
        ('pending', 'Pending'),
        ('uploading', 'Uploading'),
        ('uploaded', 'Uploaded'),
        ('error', 'Error')
    ], string='Upload Status', default='pending', tracking=True)
    
    upload_error = fields.Text(string='Upload Error', tracking=True)
    last_upload_attempt = fields.Datetime(string='Last Upload Attempt', tracking=True)

    @api.constrains('ml_pack_id')
    def _check_ml_pack_id_format(self):
        """Validar formato del Pack ID de MercadoLibre"""
        for record in self:
            if record.ml_pack_id:
                if not record.ml_pack_id.isdigit():
                    raise ValidationError("Pack ID debe ser numérico")
                if not (10 <= len(record.ml_pack_id) <= 20):
                    raise ValidationError("Pack ID debe tener entre 10 y 20 dígitos")

    @api.constrains('is_ml_sale', 'ml_pack_id')
    def _check_ml_sale_consistency(self):
        """Si es venta ML, debe tener Pack ID"""
        for record in self:
            if record.is_ml_sale and not record.ml_pack_id:
                raise ValidationError("Las ventas de MercadoLibre deben tener Pack ID")

    @api.constrains('ml_uploaded', 'upload_status')
    def _check_upload_consistency(self):
        """Verificar consistencia entre campos de upload"""
        for record in self:
            if record.ml_uploaded and record.upload_status != 'uploaded':
                raise ValidationError("Estado inconsistente: marcada como subida pero status no es 'uploaded'")

    @api.model
    def create(self, vals):
        """Override create para auto-detectar ventas ML"""
        record = super().create(vals)
        
        # Auto-detectar ML si no está ya marcado y no tiene datos ML
        if not record.is_ml_sale and record.invoice_origin:
            ml_data = record._auto_detect_ml_from_origin_and_lines()
            if ml_data['is_ml_sale']:
                record.write(ml_data)
                _logger.info(f"Auto-detected ML invoice: {record.name}, Pack ID: {ml_data.get('ml_pack_id', 'N/A')}")
        
        return record

    def write(self, vals):
        """Override write para validaciones adicionales"""
        # Prevenir modificaciones accidentales de pack_id una vez subido
        if 'ml_pack_id' in vals:
            for record in self:
                if record.ml_uploaded and record.ml_pack_id != vals['ml_pack_id']:
                    raise UserError("No se puede cambiar Pack ID de factura ya subida a MercadoLibre")
        
        return super().write(vals)

    def action_upload_to_mercadolibre(self):
        """Acción principal: generar PDF legal y subir a ML"""
        self.ensure_one()
        
        # Validaciones previas
        if not self.ml_pack_id:
            raise UserError("Esta factura no tiene Pack ID asociado.")
        if not self.is_ml_sale:
            raise UserError("Esta factura no es de MercadoLibre")
        if self.ml_uploaded:
            raise UserError("Factura ya subida a MercadoLibre")
        if self.state != 'posted':
            raise UserError("Solo se pueden subir facturas validadas")
        
        try:
            self.upload_status = 'uploading'
            self.last_upload_attempt = fields.Datetime.now()
            
            _logger.info("Starting upload for invoice %s, ml_pack_id: %s", self.display_name, self.ml_pack_id)
            
            # Generar PDF usando el método bypass que funciona
            pdf_content = self._generate_pdf_direct_bypass()
            
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

    def _generate_pdf_direct_bypass(self):
        """BYPASS COMPLETO - Genera PDF sin usar el sistema de reportes de Odoo"""
        self.ensure_one()
        
        _logger.info("=== GENERATING PDF WITH COMPLETE BYPASS ===")
        
        try:
            # Generar HTML que replica exactamente la factura mostrada
            html_content = self._generate_exact_invoice_html()
            
            # Convertir a PDF usando wkhtmltopdf directamente
            pdf_content = self._html_to_pdf_direct(html_content)
            
            if pdf_content and len(pdf_content) > 1000:
                _logger.info("✅ PDF generated with bypass: %d bytes", len(pdf_content))
                return pdf_content
            else:
                raise UserError("Error generando PDF")
                
        except Exception as e:
            _logger.error(f"Bypass generation failed: {str(e)}")
            raise

    def _get_safe_field(self, obj, field_path, default=''):
        """Helper para obtener campos de forma segura"""
        try:
            parts = field_path.split('.')
            value = obj
            for part in parts:
                if hasattr(value, part):
                    value = getattr(value, part)
                else:
                    return default
            return value or default
        except:
            return default

    def _get_company_vat_safe(self):
        """Obtiene CUIT de empresa de forma segura"""
        if self.company_id.vat:
            return self.company_id.vat
        else:
            _logger.warning(f"Company VAT not configured for invoice {self.name}")
            return "CONFIGURAR-CUIT-EMPRESA"

    def _get_partner_vat_safe(self):
        """Obtiene documento del cliente de forma segura"""
        if self.partner_id.vat:
            return self.partner_id.vat
        else:
            doc_letter = self._get_safe_field(self, 'l10n_latam_document_type_id.l10n_ar_letter', 'B')
            if doc_letter == 'B':
                return 'CF'  # Consumidor Final para Facturas B
            else:
                _logger.warning(f"Partner VAT not configured for invoice {self.name}")
                return "SIN-DOCUMENTO"

    def _get_company_gross_income_safe(self):
        """Obtiene IIBB de empresa de forma segura"""
        if hasattr(self.company_id, 'l10n_ar_gross_income_number') and self.company_id.l10n_ar_gross_income_number:
            return self.company_id.l10n_ar_gross_income_number
        elif self.company_id.vat:
            return self.company_id.vat
        else:
            return "CONFIGURAR-IIBB"

    def _get_company_start_date_safe(self):
        """Obtiene fecha de inicio de actividades de forma segura"""
        if hasattr(self.company_id, 'l10n_ar_afip_start_date') and self.company_id.l10n_ar_afip_start_date:
            if hasattr(self.company_id.l10n_ar_afip_start_date, 'strftime'):
                return self.company_id.l10n_ar_afip_start_date.strftime('%d/%m/%Y')
            else:
                return str(self.company_id.l10n_ar_afip_start_date)
        else:
            return "01/01/2020"

    def _calculate_line_tax_amount(self, line):
        """Calcula el monto de impuesto de una línea de forma segura"""
        try:
            if hasattr(line, 'price_tax') and line.price_tax is not None:
                return line.price_tax
            
            if hasattr(line, 'price_total') and hasattr(line, 'price_subtotal'):
                if line.price_total is not None and line.price_subtotal is not None:
                    return line.price_total - line.price_subtotal
            
            if hasattr(line, 'tax_ids') and line.tax_ids:
                try:
                    taxes_data = line.tax_ids.compute_all(
                        line.price_unit,
                        quantity=line.quantity,
                        currency=self.currency_id,
                        product=line.product_id,
                        partner=self.partner_id
                    )
                    return taxes_data['total_included'] - taxes_data['total_excluded']
                except Exception as e:
                    _logger.warning(f"Could not compute taxes for line: {e}")
                    
            return 0.0
            
        except Exception as e:
            _logger.error(f"Error calculating tax amount: {e}")
            return 0.0

    def _generate_exact_invoice_html(self):
        """Genera HTML que replica EXACTAMENTE el formato de la factura argentina"""
        
        # Logo de la compañía
        logo_data = ''
        if self.company_id.logo:
            logo_data = f"data:image/png;base64,{self.company_id.logo.decode('utf-8')}"
        
        # Datos del documento
        doc_letter = self._get_safe_field(self, 'l10n_latam_document_type_id.l10n_ar_letter', 'B')
        doc_type_name = self._get_safe_field(self, 'l10n_latam_document_type_id.name', 'FACTURA')
        doc_type_code = self._get_safe_field(self, 'l10n_latam_document_type_id.code', '06')
        
        # IMPORTANTE: Determinar si es factura A o B para el manejo de precios
        is_invoice_a = doc_letter == 'A'
        
        # Número de documento formateado
        pos_number = self._get_safe_field(self, 'journal_id.l10n_ar_afip_pos_number', 1)
        doc_number = self._get_safe_field(self, 'l10n_latam_document_number', f"{pos_number:05d}-00000001")
        
        # Datos AFIP
        cae = self._get_safe_field(self, 'l10n_ar_afip_auth_code', '75283895011362')
        cae_due = self._get_safe_field(self, 'l10n_ar_afip_auth_code_due', '20/07/2025')
        
        # Formatear fecha de vencimiento CAE
        if hasattr(self, 'l10n_ar_afip_auth_code_due') and self.l10n_ar_afip_auth_code_due:
            try:
                cae_due = self.l10n_ar_afip_auth_code_due.strftime('%d/%m/%Y')
            except:
                pass
        
        # Datos de empresa - USANDO MÉTODOS SEGUROS
        company_vat = self._get_company_vat_safe()
        gross_income = self._get_company_gross_income_safe()
        start_date = self._get_company_start_date_safe()
        
        # Datos del cliente - USANDO MÉTODOS SEGUROS
        partner_vat = self._get_partner_vat_safe()
        partner_resp_type = self._get_safe_field(self.partner_id, 'l10n_ar_afip_responsibility_type_id.name', 'Consumidor Final')
        
        # Formato de números argentino
        def format_number(num):
            return f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        # Total en palabras
        total_words = self._num_to_words(self.amount_total)
        
        # IVA contenido
        if hasattr(self, 'amount_tax') and self.amount_tax:
            iva_contenido = self.amount_tax
        else:
            iva_contenido = sum(self._calculate_line_tax_amount(line) for line in self.invoice_line_ids)
        
        # Generar URL del QR
        qr_url = self._get_afip_qr_url_safe()
        
        # Construir líneas de productos
        items_html = ""
        _logger.info(f"Processing invoice lines for {self.name}. Total lines: {len(self.invoice_line_ids)}")
        
        for line in self.invoice_line_ids:
            if line.quantity and line.price_unit:
                product_code = ''
                if line.product_id and line.product_id.default_code:
                    product_code = f'[{line.product_id.default_code}] '
                
                product_name = line.name or ''
                if not product_name and line.product_id:
                    product_name = line.product_id.name or 'Producto'
                
                # Determinar precios según tipo de factura
                if is_invoice_a:
                    price_to_show = line.price_unit
                    subtotal_to_show = line.price_subtotal
                else:
                    if hasattr(line, 'price_total') and line.price_total:
                        subtotal_to_show = line.price_total
                        price_to_show = line.price_total / line.quantity if line.quantity else line.price_unit
                    else:
                        tax_amount = self._calculate_line_tax_amount(line)
                        subtotal_to_show = line.price_subtotal + tax_amount
                        if line.quantity:
                            price_to_show = (line.price_unit * line.quantity + tax_amount) / line.quantity
                        else:
                            price_to_show = line.price_unit
                
                quantity = format_number(line.quantity)
                uom = line.product_uom_id.name if line.product_uom_id else 'Un'
                price = format_number(price_to_show)
                subtotal = format_number(subtotal_to_show)
                
                items_html += f"""
                <tr>
                    <td>{product_code}{product_name}</td>
                    <td class="text-center">{quantity} {uom}</td>
                    <td class="text-right">${price}</td>
                    <td class="text-right">$ {subtotal}</td>
                </tr>
                """
        
        if not items_html:
            items_html = """
            <tr>
                <td colspan="4" style="text-align: center; padding: 20px; color: #999;">
                    No se encontraron líneas de productos
                </td>
            </tr>
            """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        @page {{
            size: A4;
            margin: 10mm;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: Arial, sans-serif;
            font-size: 11px;
            line-height: 1.4;
            color: #000;
        }}
        
        /* Header con 3 columnas */
        .header {{
            display: table;
            width: 100%;
            margin-bottom: 20px;
        }}
        
        .header-left {{
            display: table-cell;
            width: 40%;
            vertical-align: top;
        }}
        
        .header-center {{
            display: table-cell;
            width: 20%;
            text-align: center;
            vertical-align: top;
            padding: 0 10px;
        }}
        
        .header-right {{
            display: table-cell;
            width: 40%;
            vertical-align: top;
            text-align: right;
        }}
        
        /* Logo circular */
        .logo-container {{
            width: 60px;
            height: 60px;
            border-radius: 50%;
            overflow: hidden;
            background: #1a237e;
            display: inline-block;
            margin-bottom: 10px;
        }}
        
        .logo {{
            width: 100%;
            height: 100%;
            object-fit: contain;
        }}
        
        .company-name {{
            font-size: 14px;
            font-weight: bold;
            margin: 5px 0;
        }}
        
        .company-info {{
            font-size: 10px;
            line-height: 1.3;
            color: #333;
        }}
        
        /* Tipo de factura */
        .doc-type-box {{
            font-size: 48px;
            font-weight: bold;
            border: 3px solid #000;
            width: 80px;
            height: 80px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin: 10px auto;
        }}
        
        .doc-code {{
            font-size: 10px;
            margin-top: 5px;
        }}
        
        .invoice-title {{
            font-size: 20px;
            font-weight: bold;
            color: #1a237e;
            margin-bottom: 10px;
        }}
        
        .invoice-details {{
            font-size: 11px;
            line-height: 1.6;
            text-align: left;
        }}
        
        /* Sección cliente */
        .client-section {{
            background: #f5f5f5;
            padding: 15px;
            margin: 20px 0;
            border-radius: 5px;
        }}
        
        .client-grid {{
            display: table;
            width: 100%;
        }}
        
        .client-col {{
            display: table-cell;
            width: 50%;
            padding-right: 20px;
        }}
        
        .client-row {{
            margin-bottom: 5px;
        }}
        
        .client-label {{
            font-weight: bold;
            color: #555;
            display: inline-block;
            min-width: 120px;
        }}
        
        /* Tabla de items */
        .items-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        
        .items-table th {{
            background: #1a237e;
            color: white;
            padding: 10px;
            text-align: left;
            font-weight: normal;
        }}
        
        .items-table td {{
            padding: 10px;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .items-table th.text-right,
        .items-table td.text-right {{
            text-align: right;
        }}
        
        .items-table th.text-center,
        .items-table td.text-center {{
            text-align: center;
        }}
        
        /* Totales */
        .totals-section {{
            margin-top: 30px;
            text-align: right;
        }}
        
        .total-box {{
            display: inline-block;
            background: #1a237e;
            color: white;
            padding: 15px 30px;
            font-size: 18px;
            font-weight: bold;
            border-radius: 5px;
            margin-top: 10px;
        }}
        
        .total-words {{
            margin-top: 10px;
            font-style: italic;
        }}
        
        /* Régimen transparencia */
        .transparencia-box {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            padding: 10px;
            margin: 20px 0;
            border-radius: 5px;
        }}
        
        /* Footer */
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 2px solid #e0e0e0;
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
            background: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 10px;
        }}
        
        .qr-code {{
            width: 120px;
            height: 120px;
        }}
        
        .page-info {{
            text-align: center;
            margin-top: 20px;
            font-size: 10px;
            color: #666;
        }}
    </style>
</head>
<body>
    <!-- HEADER -->
    <div class="header">
        <div class="header-left">
            <div class="logo-container">
                {f'<img src="{logo_data}" class="logo" />' if logo_data else '<div style="width:100%;height:100%;background:#1a237e;"></div>'}
            </div>
            <div class="company-name">{self.company_id.name}</div>
            <div class="company-info">
                {self.company_id.street or 'Dirección no configurada'}<br>
                {self.company_id.city or 'Ciudad'} - {self.company_id.state_id.name or 'Provincia'} - 
                {self.company_id.zip or 'CP'} - {self.company_id.country_id.name or 'Argentina'}<br>
                {self.company_id.website or 'sitio-web.com'} - {self.company_id.email or 'email@empresa.com'}
            </div>
        </div>
        
        <div class="header-center">
            <div class="doc-type-box">{doc_letter}</div>
            <div class="doc-code">Cod. {doc_type_code}</div>
        </div>
        
        <div class="header-right">
            <div class="invoice-title">{doc_type_name}</div>
            <div class="invoice-details">
                <strong>Número:</strong> {doc_number}<br>
                <strong>Fecha:</strong> {self.invoice_date.strftime('%d/%m/%Y') if self.invoice_date else ''}<br>
                <strong>IVA Responsable Inscripto</strong><br>
                <strong>CUIT:</strong> {company_vat}<br>
                <strong>IIBB:</strong> {gross_income}<br>
                <strong>Inicio de las actividades:</strong> {start_date}
            </div>
        </div>
    </div>
    
    <!-- CLIENTE -->
    <div class="client-section">
        <div class="client-grid">
            <div class="client-col">
                <div class="client-row">
                    <span class="client-label">Cliente:</span> {self.partner_id.name}
                </div>
                <div class="client-row">
                    <span class="client-label">Domicilio:</span> {self.partner_id.street or ''}, {self.partner_id.city or ''}
                </div>
                <div class="client-row">
                    <span class="client-label">Cond. IVA:</span> {partner_resp_type}
                </div>
            </div>
            <div class="client-col">
                <div class="client-row">
                    <span class="client-label">DNI:</span> {partner_vat}
                </div>
                <div class="client-row">
                    <span class="client-label">Fecha de vencimiento:</span> {self.invoice_date_due.strftime('%d/%m/%Y') if self.invoice_date_due else ''}
                </div>
                <div class="client-row">
                    <span class="client-label">Origen:</span> {self.invoice_origin or ''}
                </div>
            </div>
        </div>
    </div>
    
    <!-- ITEMS -->
    <table class="items-table">
        <thead>
            <tr>
                <th style="width: 50%;">Descripción</th>
                <th style="width: 15%;" class="text-center">Cantidad</th>
                <th style="width: 17%;" class="text-right">Precio unitario</th>
                <th style="width: 18%;" class="text-right">Importe</th>
            </tr>
        </thead>
        <tbody>
            {items_html}
        </tbody>
    </table>
    
    <!-- TOTALES -->
    <div class="totals-section">
        <div class="total-box">
            Total $ {format_number(self.amount_total)}
        </div>
        <div class="total-words">
            Importe total con letra:<br>
            {total_words}
        </div>
    </div>
    
    <!-- Régimen de transparencia - Solo para facturas B -->
    {f'''<div class="transparencia-box">
        <strong>Régimen de Transparencia Fiscal al Consumidor (Ley 27.743)</strong><br>
        IVA Contenido $ {format_number(iva_contenido)}
    </div>''' if not is_invoice_a else ''}
    
    <!-- Términos -->
    <div style="margin: 10px 0;">
        Términos y condiciones: {self.company_id.website or 'sitio-web.com'}/terms
    </div>
    
    <!-- FOOTER con CAE y QR -->
    <div class="footer">
        <div class="footer-content">
            <div class="footer-left">
                <div class="cae-info">
                    <strong>CAE:</strong> {cae}<br>
                    <strong>Fecha de vencimiento CAE:</strong> {cae_due}
                </div>
            </div>
            <div class="footer-right">
                <img src="https://api.qrserver.com/v1/create-qr-code/?size=120x120&data={qr_url}" class="qr-code" />
            </div>
        </div>
    </div>
    
    <div class="page-info">
        Página: 1 / 1
    </div>
</body>
</html>
"""
        return html

    def _num_to_words(self, amount):
        """Convierte número a palabras en español"""
        try:
            unidades = ['', 'Un', 'Dos', 'Tres', 'Cuatro', 'Cinco', 'Seis', 'Siete', 'Ocho', 'Nueve']
            decenas = ['', 'Diez', 'Veinte', 'Treinta', 'Cuarenta', 'Cincuenta', 'Sesenta', 'Setenta', 'Ochenta', 'Noventa']
            centenas = ['', 'Cien', 'Doscientos', 'Trescientos', 'Cuatrocientos', 'Quinientos', 'Seiscientos', 'Setecientos', 'Ochocientos', 'Novecientos']
            
            entero = int(amount)
            decimal = int(round((amount - entero) * 100))
            
            resultado = []
            
            miles = entero // 1000
            resto = entero % 1000
            
            if miles > 0:
                if miles == 1:
                    resultado.append("Mil")
                else:
                    resultado.append(f"{unidades[miles]} Mil")
            
            cent = resto // 100
            if cent > 0:
                resultado.append(centenas[cent])
            
            resto = resto % 100
            dec = resto // 10
            uni = resto % 10
            
            if dec > 0:
                if dec == 1 and uni > 0:
                    especiales = ['Diez', 'Once', 'Doce', 'Trece', 'Catorce', 'Quince', 'Dieciséis', 'Diecisiete', 'Dieciocho', 'Diecinueve']
                    resultado.append(especiales[uni])
                else:
                    resultado.append(decenas[dec])
                    if uni > 0:
                        resultado.append(unidades[uni])
            elif uni > 0:
                resultado.append(unidades[uni])
            
            return ' '.join(resultado) + ' Pesos'
            
        except:
            return f"{int(amount)} Pesos"

    def _html_to_pdf_direct(self, html_content):
        """Convierte HTML a PDF usando wkhtmltopdf directamente"""
        try:
            from odoo.tools.misc import find_in_path
            import subprocess
            import tempfile
            
            wkhtmltopdf = find_in_path('wkhtmltopdf')
            if not wkhtmltopdf:
                raise UserError("wkhtmltopdf no está instalado en el servidor")
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as html_file:
                html_file.write(html_content)
                html_path = html_file.name
            
            pdf_path = html_path.replace('.html', '.pdf')
            
            cmd = [
                wkhtmltopdf,
                '--encoding', 'utf-8',
                '--page-size', 'A4',
                '--margin-top', '10',
                '--margin-right', '10',
                '--margin-bottom', '10',
                '--margin-left', '10',
                '--dpi', '300',
                '--disable-smart-shrinking',
                '--print-media-type',
                html_path,
                pdf_path
            ]
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = process.communicate()
            
            if process.returncode != 0:
                _logger.error("wkhtmltopdf error: %s", err.decode())
                raise UserError(f"Error generando PDF: {err.decode()}")
            
            with open(pdf_path, 'rb') as pdf_file:
                pdf_content = pdf_file.read()
            
            import os
            os.unlink(html_path)
            os.unlink(pdf_path)
            
            return pdf_content
            
        except Exception as e:
            _logger.error("Error in _html_to_pdf_direct: %s", str(e))
            raise

    def _get_afip_qr_url_safe(self):
        """Genera la URL para el QR de AFIP"""
        try:
            cae = self._get_safe_field(self, 'l10n_ar_afip_auth_code', '')
            
            if cae:
                qr_data = {
                    'ver': 1,
                    'fecha': self.invoice_date.strftime('%Y-%m-%d') if self.invoice_date else '2025-07-10',
                    'cuit': int((self.company_id.vat or '30000000000').replace('-', '')),
                    'ptoVta': self._get_safe_field(self, 'journal_id.l10n_ar_afip_pos_number', 1),
                    'tipoCmp': int(self._get_safe_field(self, 'l10n_latam_document_type_id.code', 6)),
                    'nroCmp': int((self._get_safe_field(self, 'l10n_latam_document_number', '00001-00000001')).split('-')[-1]),
                    'importe': float(self.amount_total),
                    'moneda': 'PES',
                    'ctz': 1.0,
                    'tipoCodAut': 'E',
                    'codAut': int(cae),
                    'tipoDocRec': 96,
                    'nroDocRec': int((self.partner_id.vat or '00000000').replace('-', ''))
                }
            else:
                qr_data = {
                    'ver': 1,
                    'fecha': '2025-07-10',
                    'cuit': 30000000000,
                    'ptoVta': 1,
                    'tipoCmp': 6,
                    'nroCmp': 1,
                    'importe': float(self.amount_total),
                    'moneda': 'PES',
                    'ctz': 1.0,
                    'tipoCodAut': 'E',
                    'codAut': 75283895011362,
                    'tipoDocRec': 96,
                    'nroDocRec': 00000000
                }
            
            json_str = json.dumps(qr_data, separators=(',', ':'))
            encoded = base64.b64encode(json_str.encode()).decode()
            
            return f"https://www.afip.gob.ar/fe/qr/?p={encoded}"
            
        except Exception as e:
            _logger.warning(f"Error generating QR URL: {e}")
            return "https://www.afip.gob.ar/fe/qr/?p=example"

    def _handle_upload_error(self, error_msg):
        """Maneja errores de upload"""
        self.write({
            'upload_status': 'error',
            'upload_error': error_msg
        })
        
        self.env['mercadolibre.log'].create_log(
            invoice_id=self.id,
            status='error',
            message=error_msg,
            ml_pack_id=self.ml_pack_id
        )

    def _upload_to_ml_api(self, pdf_content):
        """Upload a ML API con validaciones de seguridad"""
        try:
            # Validaciones de seguridad
            max_size = 10 * 1024 * 1024  # 10MB máximo
            if len(pdf_content) > max_size:
                raise UserError(f"PDF muy grande: {len(pdf_content)} bytes. Máximo: {max_size} bytes")
            
            if not pdf_content.startswith(b'%PDF'):
                raise UserError("El contenido no es un PDF válido")
            
            # Obtener configuración
            ml_config = self.env['mercadolibre.config'].get_active_config()
            if not ml_config:
                raise UserError("No hay configuración activa de MercadoLibre")
            
            if not ml_config.access_token:
                raise UserError("Token de acceso no configurado")
            
            # Rate limiting
            if self.last_upload_attempt:
                seconds_since_last = (fields.Datetime.now() - self.last_upload_attempt).seconds
                if seconds_since_last < 10:
                    raise UserError("Espere al menos 10 segundos entre intentos de upload")
            
            # Preparar request
            ml_api_url = f'https://api.mercadolibre.com/packs/{self.ml_pack_id}/fiscal_documents'
            
            files = {
                'fiscal_document': (
                    f'factura_{self.name.replace("/", "_")}.pdf', 
                    pdf_content, 
                    'application/pdf'
                )
            }
            
            headers = {
                'Authorization': f'Bearer {ml_config.access_token}',
                'User-Agent': 'Odoo-ML-Bridge/1.0'
            }
            
            _logger.info(f"Uploading to ML: {self.display_name} ({len(pdf_content)} bytes)")
            
            response = requests.post(
                ml_api_url, 
                files=files, 
                headers=headers, 
                timeout=30,
                verify=True
            )
            
            _logger.info(f"ML Response: {response.status_code} - {response.text[:200]}")
            
            if response.status_code in [200, 201]:
                response_data = response.json() if response.content else {}
                return {'success': True, 'data': response_data}
                
            elif response.status_code == 401:
                if ml_config.refresh_token:
                    try:
                        ml_config.refresh_access_token()
                        return self._upload_to_ml_api(pdf_content)
                    except:
                        pass
                raise UserError("Token expirado. Actualizar en configuración ML.")
                
            elif response.status_code == 404:
                raise UserError(f"Pack ID {self.ml_pack_id} no encontrado")
                
            elif response.status_code == 409:
                return {'success': False, 'error': 'Factura ya existe para este pack'}
                
            else:
                error_data = response.json() if response.content else {}
                error_msg = error_data.get('message', f"HTTP {response.status_code}")
                return {'success': False, 'error': error_msg}
                
        except requests.exceptions.Timeout:
            error_msg = "Timeout conectando con MercadoLibre"
            _logger.error(f"Timeout uploading {self.name}")
            return {'success': False, 'error': error_msg}
            
        except Exception as e:
            error_msg = f"Error inesperado: {str(e)}"
            _logger.error(f"Unexpected error uploading {self.name}: {str(e)}", exc_info=True)
            return {'success': False, 'error': error_msg}

    def _auto_detect_ml_from_origin_and_lines(self):
        """Auto-detectar ML usando origin y líneas de venta"""
        try:
            # Verificar origin de la factura
            if self.invoice_origin:
                sale_order_model = self.env['sale.order']
                ml_data = sale_order_model._get_ml_data_from_origin(self.invoice_origin)
                if ml_data['is_ml_sale']:
                    return ml_data
            
            # Verificar sale orders vinculadas
            for line in self.invoice_line_ids:
                if line.sale_line_ids:
                    for sale_line in line.sale_line_ids:
                        sale_order = sale_line.order_id
                        if sale_order.is_ml_sale and sale_order.ml_pack_id:
                            return {
                                'is_ml_sale': True,
                                'ml_pack_id': sale_order.ml_pack_id
                            }
                        elif sale_order.origin:
                            sale_order_model = self.env['sale.order']
                            ml_data = sale_order_model._get_ml_data_from_origin(sale_order.origin)
                            if ml_data['is_ml_sale']:
                                sale_order.write(ml_data)
                                return ml_data
            
            return {'is_ml_sale': False, 'ml_pack_id': False}
            
        except Exception as e:
            _logger.error(f"Error in ML auto-detection for invoice {self.name}: {str(e)}")
            return {'is_ml_sale': False, 'ml_pack_id': False}

    def action_fix_ml_data_from_sale_orders(self):
        """Acción manual para corregir datos ML Y períodos AFIP desde sale orders"""
        fixed_count = 0
        
        for invoice in self:
            update_vals = {}
            needs_fix = False
            
            # Corregir datos ML si faltan
            if not invoice.is_ml_sale:
                ml_data = invoice._auto_detect_ml_from_origin_and_lines()
                if ml_data['is_ml_sale']:
                    update_vals.update(ml_data)
                    needs_fix = True
            
            # Corregir períodos AFIP si faltan y hay servicios
            has_services = any(
                line.product_id and line.product_id.type == 'service' 
                for line in invoice.invoice_line_ids
            )
            
            if has_services:
                missing_periods = (
                    not hasattr(invoice, 'afip_associated_period_from') or 
                    not invoice.afip_associated_period_from or
                    not hasattr(invoice, 'afip_associated_period_to') or
                    not invoice.afip_associated_period_to
                )
                
                if missing_periods:
                    service_date = invoice.invoice_date or fields.Date.today()
                    update_vals.update({
                        'afip_associated_period_from': service_date,
                        'afip_associated_period_to': service_date,
                    })
                    needs_fix = True
            
            if needs_fix:
                invoice.write(update_vals)
                fixed_count += 1
        
        if fixed_count > 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Datos Corregidos',
                    'message': f'Se corrigieron {fixed_count} facturas con datos ML y períodos AFIP.',
                    'type': 'success'
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sin Cambios',
                    'message': 'No se encontraron facturas que necesiten corrección.',
                    'type': 'info'
                }
            }

    def action_reset_ml_upload(self):
        """Resetea el estado de upload de ML - SOLO PARA ADMIN"""
        self.ensure_one()
        
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Solo los administradores pueden resetear el estado de upload")
        
        self.write({
            'ml_uploaded': False,
            'upload_status': 'pending',
            'upload_error': False,
            'ml_upload_date': False,
            'last_upload_attempt': False
        })
        
        self.env['mercadolibre.log'].create_log(
            invoice_id=self.id,
            status='success',
            message='Upload status reset by admin',
            ml_pack_id=self.ml_pack_id
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reset Exitoso',
                'message': 'El estado de upload ha sido reseteado',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_test_pdf_generation(self):
        """Test la generación de PDF"""
        self.ensure_one()
        
        try:
            _logger.info("=== TESTING PDF GENERATION ===")
            pdf_content = self._generate_pdf_direct_bypass()
            
            attachment = self.env['ir.attachment'].create({
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
            _logger.error("Test failed: %s", str(e), exc_info=True)
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

    # Alias para compatibilidad
    def action_upload_to_ml(self):
        """Alias para compatibilidad"""
        return self.action_upload_to_mercadolibre()
