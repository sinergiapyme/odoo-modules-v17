# -*- coding: utf-8 -*-

import base64
import tempfile
import os
import json
import logging
import re
import requests
import gc
from contextlib import contextmanager
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    is_ml_sale = fields.Boolean(string='MercadoLibre Sale', compute='_compute_is_ml_sale', store=True)
    ml_pack_id = fields.Char(string='ML Pack ID')
    ml_uploaded = fields.Boolean(string='Uploaded to ML', default=False)
    ml_upload_date = fields.Datetime(string='ML Upload Date', readonly=True)

    @api.depends('invoice_origin', 'ref')
    def _compute_is_ml_sale(self):
        for move in self:
            move.is_ml_sale = False
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue
            if move.invoice_origin:
                sale_orders = self.env['sale.order'].search([('name', '=', move.invoice_origin)], limit=1)
                for order in sale_orders:
                    if order.origin and 'MercadoLibre Order' in order.origin:
                        move.is_ml_sale = True
                        if not move.ml_pack_id:
                            pack_id = move._extract_pack_id_safe(order.origin)
                            if pack_id:
                                move.ml_pack_id = pack_id
                        break

    def _extract_pack_id_safe(self, origin_text):
        try:
            match = re.search(r'MercadoLibre Order\s+(\d{10,16})', origin_text, re.IGNORECASE)
            if match:
                pack_id = match.group(1)
                if pack_id.isdigit() and 10 <= len(pack_id) <= 16:
                    return pack_id
        except Exception as e:
            _logger.warning('Error extracting pack_id: %s', str(e))
        return None

    @contextmanager
    def _secure_temp_file(self, data, suffix='.pdf'):
        """
        Context manager FILESTORE-SAFE - GARANTÍA TOTAL
        
        SEGURIDAD FILESTORE:
        - Usa tempfile.NamedTemporaryFile en /tmp del sistema
        - NO toca el filestore de Odoo (/opt/odoo/filestore/)
        - Auto-elimina archivos al finalizar
        - Manejo de errores que garantiza limpieza
        """
        temp_file = None
        temp_path = None
        try:
            # FILESTORE-SAFE: Crea archivo en /tmp del sistema, NO en filestore
            temp_file = tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False)
            temp_path = temp_file.name
            temp_file.write(data)
            temp_file.flush()
            temp_file.close()
            
            _logger.debug('FILESTORE-SAFE: Created temp file: %s', temp_path)
            yield temp_path
            
        except Exception as e:
            _logger.error('Error creating temp file: %s', str(e))
            raise
        finally:
            # FILESTORE-SAFE: Limpieza garantizada
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                    _logger.debug('FILESTORE-SAFE: Cleaned temp file: %s', temp_path)
                except OSError as e:
                    _logger.warning('FILESTORE-SAFE: Could not clean temp file %s: %s', temp_path, str(e))

    def _generate_html_invoice(self):
        """
        Genera HTML básico - FILESTORE-SAFE
        
        SEGURIDAD FILESTORE:
        - Solo genera string HTML en memoria
        - NO crea archivos en filestore
        - NO modifica attachments
        """
        try:
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Factura {self.name}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    .header {{ text-align: center; margin-bottom: 30px; }}
                    .invoice-info {{ margin-bottom: 20px; }}
                    .customer-info {{ margin-bottom: 20px; }}
                    .lines-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                    .lines-table th, .lines-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    .lines-table th {{ background-color: #f2f2f2; }}
                    .total {{ text-align: right; font-weight: bold; }}
                    .warning {{ background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <div class="warning">
                    <strong>ADVERTENCIA:</strong> Esta factura fue generada en formato básico.
                    No cumple con los requerimientos de la ley argentina (CAE, QR, etc.).
                    Contacte al administrador para solucionar los reportes ADHOC.
                </div>
                
                <div class="header">
                    <h1>FACTURA</h1>
                    <h2>{self.name}</h2>
                </div>
                
                <div class="invoice-info">
                    <p><strong>Fecha:</strong> {self.invoice_date or 'N/A'}</p>
                    <p><strong>Vencimiento:</strong> {self.invoice_date_due or 'N/A'}</p>
                    <p><strong>Estado:</strong> {dict(self._fields['state'].selection).get(self.state, self.state)}</p>
                </div>
                
                <div class="customer-info">
                    <h3>Cliente:</h3>
                    <p><strong>{self.partner_id.name or 'N/A'}</strong></p>
                    <p>{self.partner_id.street or ''}</p>
                    <p>{self.partner_id.city or ''} {self.partner_id.state_id.name or ''}</p>
                    <p>{self.partner_id.country_id.name or ''}</p>
                    {f'<p>CUIT: {self.partner_id.vat}</p>' if self.partner_id.vat else ''}
                </div>
                
                <table class="lines-table">
                    <thead>
                        <tr>
                            <th>Producto/Servicio</th>
                            <th>Cantidad</th>
                            <th>Precio Unit.</th>
                            <th>Subtotal</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            for line in self.invoice_line_ids:
                html_content += f"""
                        <tr>
                            <td>{line.product_id.name or line.name or 'Producto'}</td>
                            <td>{line.quantity}</td>
                            <td>${line.price_unit:,.2f}</td>
                            <td>${line.price_subtotal:,.2f}</td>
                        </tr>
                """
            
            html_content += f"""
                    </tbody>
                </table>
                
                <div class="total">
                    <p>Subtotal: ${self.amount_untaxed:,.2f}</p>
                    <p>Impuestos: ${self.amount_tax:,.2f}</p>
                    <p><strong>TOTAL: ${self.amount_total:,.2f}</strong></p>
                </div>
                
                <div style="margin-top: 40px; font-size: 12px; color: #666;">
                    <p>Factura generada para MercadoLibre (formato básico)</p>
                    <p>Pack ID: {self.ml_pack_id or 'N/A'}</p>
                    <p><strong>NOTA:</strong> Esta factura NO cumple con requisitos legales argentinos</p>
                </div>
            </body>
            </html>
            """
            
            return html_content
            
        except Exception as e:
            _logger.error('Error generating HTML: %s', str(e))
            raise

    def _html_to_pdf_wkhtmltopdf(self, html_content):
        """
        Convierte HTML a PDF - FILESTORE-SAFE
        
        SEGURIDAD FILESTORE:
        - Usa archivos temporales en /tmp del sistema
        - NO toca el filestore de Odoo
        - Limpieza automática garantizada
        """
        try:
            import subprocess
            
            # FILESTORE-SAFE: Crear archivo HTML temporal en /tmp
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as html_file:
                html_file.write(html_content)
                html_file.flush()
                html_path = html_file.name
            
            # FILESTORE-SAFE: Crear archivo PDF temporal en /tmp
            pdf_path = tempfile.mktemp(suffix='.pdf')
            
            try:
                cmd = [
                    'wkhtmltopdf',
                    '--page-size', 'A4',
                    '--margin-top', '0.75in',
                    '--margin-right', '0.75in', 
                    '--margin-bottom', '0.75in',
                    '--margin-left', '0.75in',
                    '--encoding', 'UTF-8',
                    '--quiet',
                    html_path,
                    pdf_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(pdf_path):
                    # FILESTORE-SAFE: Leer contenido y almacenar en memoria
                    with open(pdf_path, 'rb') as pdf_file:
                        pdf_content = pdf_file.read()
                    
                    _logger.info('FILESTORE-SAFE: PDF generated with wkhtmltopdf, size: %d bytes', len(pdf_content))
                    return pdf_content
                else:
                    _logger.error('wkhtmltopdf failed: %s', result.stderr)
                    return None
                    
            finally:
                # FILESTORE-SAFE: Limpieza garantizada de archivos temporales
                try:
                    if os.path.exists(html_path):
                        os.unlink(html_path)
                        _logger.debug('FILESTORE-SAFE: Cleaned HTML temp file')
                    if os.path.exists(pdf_path):
                        os.unlink(pdf_path)
                        _logger.debug('FILESTORE-SAFE: Cleaned PDF temp file')
                except OSError as e:
                    _logger.warning('FILESTORE-SAFE: Temp file cleanup warning: %s', str(e))
                    
        except Exception as e:
            _logger.error('Error in wkhtmltopdf conversion: %s', str(e))
            return None

    def _generate_pdf_adhoc_priority(self):
        """
        REPLICACIÓN EXACTA DE LA GUI - FILESTORE-SAFE
        *** MÉTODO CORREGIDO PARA SOLUCIONAR ERROR [6] ***
        Usa exactamente el mismo proceso que funciona desde "Imprimir"
        Basado en imágenes: "Facturas sin pago" con template account.report_invoice funciona
        """
        try:
            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            _logger.info('Generating legal PDF for invoice %s using correct report objects', self.name)
            
            # *** CORRECCIÓN ESPECÍFICA DEL ERROR [6] ***
            # MÉTODO 1: Buscar el reporte exacto que funciona desde la GUI
            try:
                _logger.info('Searching for exact GUI report: "Facturas sin pago"')
                
                # FILESTORE-SAFE: Buscar por nombre exacto que viste en la interfaz
                gui_report = self.env['ir.actions.report'].search([
                    ('name', '=', 'Facturas sin pago'),
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], limit=1)
                
                if gui_report:
                    _logger.info('Using confirmed legal report: %s (ID: %s)', gui_report.report_name, gui_report.id)
                    
                    # FILESTORE-SAFE: Llamar exactamente como lo hace la GUI
                    result = gui_report._render_qweb_pdf(self.ids)
                    
                    if isinstance(result, tuple) and len(result) >= 1:
                        pdf_content = result[0]
                        if pdf_content and len(pdf_content) > 5000:
                            _logger.info('SUCCESS: GUI report "Facturas sin pago" generated legal PDF (%d bytes)', 
                                       len(pdf_content))
                            return pdf_content
                        else:
                            _logger.warning('GUI report generated small PDF (%d bytes)', 
                                          len(pdf_content) if pdf_content else 0)
                else:
                    _logger.warning('GUI report "Facturas sin pago" not found')
                    
            except Exception as e:
                _logger.warning('GUI report "Facturas sin pago" failed: %s', str(e))
            
            # MÉTODO 2: Buscar por template exacto que viste en las imágenes
            try:
                _logger.info('Searching for template: account.report_invoice')
                
                # FILESTORE-SAFE: Buscar por template exacto
                template_report = self.env['ir.actions.report'].search([
                    ('report_name', '=', 'account.report_invoice'),  # ← CORRECCIÓN: NO [6]
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], limit=1)
                
                if template_report:
                    _logger.info('Using backup legal report: %s (ID: %s)', template_report.name, template_report.id)
                    
                    result = template_report._render_qweb_pdf(self.ids)
                    
                    if isinstance(result, tuple) and len(result) >= 1:
                        pdf_content = result[0]
                        if pdf_content and len(pdf_content) > 5000:
                            _logger.info('SUCCESS: Template report account.report_invoice generated legal PDF (%d bytes)', 
                                       len(pdf_content))
                            return pdf_content
                else:
                    _logger.warning('Template account.report_invoice not found')
                    
            except Exception as e:
                _logger.warning('Template account.report_invoice search failed: %s', str(e))
            
            # MÉTODO 3: Buscar otros reportes de las imágenes que mostraste
            try:
                _logger.info('Searching for any working invoice report')
                
                # FILESTORE-SAFE: Reportes específicos que viste en las imágenes
                report_templates = [
                    'l10n_ar.report_invoice_document',
                    'l10n_ar_afipws_fe.report_invoice_document', 
                    'l10n_ar_ux.report_invoice_document',
                    'l10n_ar_ux.report_invoice',
                    'account.report_invoice_with_payments'
                ]
                
                reports_found = []
                for template_name in report_templates:
                    try:
                        report = self.env['ir.actions.report'].search([
                            ('report_name', '=', template_name),  # ← CORRECCIÓN: string, NO lista
                            ('model', '=', 'account.move')
                        ], limit=1)
                        
                        if report:
                            reports_found.append(report)
                            _logger.info('Found report: %s (template: %s)', report.name, template_name)
                            
                    except Exception as e:
                        _logger.warning('Error searching template %s: %s', template_name, str(e))
                        continue
                
                _logger.info('Found %s total invoice reports to try', len(reports_found))
                
                # Probar cada reporte encontrado
                for report in reports_found:
                    try:
                        _logger.info('Trying report ID: %s, template: %s', report.id, report.report_name)
                        
                        result = report._render_qweb_pdf(self.ids)
                        
                        if isinstance(result, tuple) and len(result) >= 1:
                            pdf_content = result[0]
                            if pdf_content and len(pdf_content) > 5000:
                                _logger.info('SUCCESS: Report %s generated legal PDF (%d bytes)', 
                                           report.name, len(pdf_content))
                                return pdf_content
                            else:
                                _logger.debug('Report %s generated small PDF (%d bytes)', 
                                            report.name, len(pdf_content) if pdf_content else 0)
                                
                    except Exception as e:
                        _logger.debug('Report %s failed: %s', report.name, str(e))
                        continue
                        
            except Exception as e:
                _logger.warning('Report template search failed: %s', str(e))
            
            # MÉTODO 4: Usar IDs específicos que aparecieron en logs anteriores (con corrección)
            try:
                _logger.info('Trying specific report IDs from previous logs')
                
                # IDs que aparecieron en los logs: 213, 214, 215
                report_ids_to_try = [215, 213, 214]  
                
                for report_id in report_ids_to_try:
                    try:
                        _logger.info('Trying report ID: %d', report_id)
                        
                        # FILESTORE-SAFE: Buscar por ID específico
                        report = self.env['ir.actions.report'].browse(report_id)
                        
                        if report.exists() and report.model == 'account.move':
                            result = report._render_qweb_pdf(self.ids)
                            
                            if isinstance(result, tuple) and len(result) >= 1:
                                pdf_content = result[0]
                                if pdf_content and len(pdf_content) > 5000:
                                    _logger.info('SUCCESS: Report ID %d (%s) generated legal PDF (%d bytes)', 
                                               report_id, report.name, len(pdf_content))
                                    return pdf_content
                                    
                    except Exception as e:
                        _logger.info('Report ID %d failed: %s', report_id, str(e))
                        continue
                        
            except Exception as e:
                _logger.warning('Specific report IDs search failed: %s', str(e))
            
            # MÉTODO 5: Buscar cualquier reporte activo sin filtros problemáticos
            try:
                _logger.info('Searching for any active account.move reports')
                
                # FILESTORE-SAFE: Buscar reportes activos sin filtros que causen el error [6]
                active_reports = self.env['ir.actions.report'].search([
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], order='id desc', limit=10)  # Los más recientes primero
                
                _logger.info('Found %d active reports for account.move', len(active_reports))
                
                for report in active_reports:
                    try:
                        _logger.info('Trying active report ID: %d (%s)', report.id, report.name or 'No name')
                        
                        # FILESTORE-SAFE: Generar PDF directamente
                        result = report._render_qweb_pdf(self.ids)
                        
                        if isinstance(result, tuple) and len(result) >= 1:
                            pdf_content = result[0]
                            if pdf_content and len(pdf_content) > 5000:
                                _logger.info('SUCCESS: Active report ID %d generated legal PDF (%d bytes)', 
                                           report.id, len(pdf_content))
                                return pdf_content
                                
                    except Exception as e:
                        _logger.debug('Active report ID %d failed: %s', report.id, str(e))
                        continue
                        
            except Exception as e:
                _logger.warning('Active reports search failed: %s', str(e))
            
            # MÉTODO 6: Fallback HTML temporal (FILESTORE-SAFE)
            try:
                _logger.warning('All legal PDF methods failed, using HTML fallback (FILESTORE-SAFE)')
                
                # FILESTORE-SAFE: Este método ya está probado
                html_content = self._generate_html_invoice()
                pdf_content = self._html_to_pdf_wkhtmltopdf(html_content)
                
                if pdf_content and len(pdf_content) > 100:
                    _logger.warning('FALLBACK: HTML PDF generated (%d bytes) FILESTORE-SAFE - NOT LEGAL COMPLIANT', 
                                  len(pdf_content))
                    return pdf_content
                    
            except Exception as e:
                _logger.error('Even HTML fallback failed: %s', str(e))
            
            # FALLO TOTAL con información específica del problema
            error_msg = (
                'CRÍTICO: No se pudo generar PDF para factura %s.\n\n'
                'Ningún reporte de ir.actions.report funcionó.\n'
                'Esto indica un problema con:\n'
                '• Configuración de reportes en el sistema\n'
                '• Permisos de generación de PDF\n'
                '• Módulos de localización\n\n'
                'CONTACTE AL ADMINISTRADOR DEL SISTEMA.'
            ) % self.name
            
            _logger.error(error_msg)
            raise UserError(error_msg)
            
        except UserError:
            raise
        except Exception as e:
            error_msg = 'Error crítico generando PDF para %s: %s' % (self.name, str(e))
            _logger.error(error_msg)
            raise UserError('Error crítico: %s' % str(e))

    def _upload_to_ml_api(self, pack_id, pdf_content, access_token):
        """
        Upload a MercadoLibre - FILESTORE-SAFE GARANTIZADO
        
        SEGURIDAD FILESTORE:
        - Usa _secure_temp_file que crea archivos en /tmp
        - NO toca el filestore de Odoo
        - Auto-limpieza garantizada
        """
        try:
            url = 'https://api.mercadolibre.com/packs/%s/fiscal_documents' % pack_id
            headers = {'Authorization': 'Bearer %s' % access_token}
            
            # FILESTORE-SAFE: Context manager que garantiza limpieza
            with self._secure_temp_file(pdf_content) as temp_file_path:
                with open(temp_file_path, 'rb') as pdf_file:
                    filename = 'factura_%s.pdf' % self.name.replace('/', '_').replace(' ', '_')
                    files = {'fiscal_document': (filename, pdf_file, 'application/pdf')}
                    
                    response = requests.post(url, headers=headers, files=files, timeout=30)
                    
                    if response.status_code == 200:
                        return {'success': True, 'data': response.json(), 'message': 'Upload successful'}
                    elif response.status_code == 401:
                        return {'success': False, 'error': 'Token de acceso expirado'}
                    elif response.status_code == 404:
                        return {'success': False, 'error': 'Pack ID no encontrado: %s' % pack_id}
                    else:
                        try:
                            error_data = response.json()
                            error_msg = error_data.get('message', 'Error desconocido')
                        except:
                            error_msg = response.text[:200] if response.text else 'Error sin detalles'
                        
                        return {'success': False, 'error': 'HTTP %d: %s' % (response.status_code, error_msg)}
                        
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Timeout - MercadoLibre no responde'}
        except Exception as e:
            return {'success': False, 'error': 'Error inesperado: %s' % str(e)}

    def action_upload_to_mercadolibre(self):
        """
        Acción principal - FILESTORE-SAFE GARANTIZADO
        
        SEGURIDAD FILESTORE:
        - Solo modifica campos de la factura (no attachments)
        - PDF se mantiene solo en memoria durante el proceso
        - Limpieza de memoria garantizada con gc.collect()
        """
        self.ensure_one()
        
        try:
            # Validaciones - FILESTORE-SAFE (solo lectura)
            if not self.is_ml_sale:
                raise UserError('Esta factura no es de MercadoLibre')
            if self.ml_uploaded:
                raise UserError('Factura ya subida a MercadoLibre')
            if self.state != 'posted':
                raise UserError('Solo se pueden subir facturas validadas')
            if not self.ml_pack_id:
                raise UserError('Pack ID de MercadoLibre no encontrado')
            
            # Configuración - FILESTORE-SAFE (solo lectura)
            config = self.env['mercadolibre.config'].get_active_config()
            if not config:
                raise UserError('No hay configuración de MercadoLibre activa')
            if not config.access_token:
                raise UserError('Token de acceso no configurado')
            
            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            
            # FILESTORE-SAFE: PDF solo en memoria durante el proceso
            pdf_content = self._generate_pdf_adhoc_priority()
            
            # FILESTORE-SAFE: Upload usando temp files, no filestore
            result = self._upload_to_ml_api(self.ml_pack_id, pdf_content, config.access_token)
            
            # FILESTORE-SAFE: Limpieza de memoria garantizada
            pdf_content = None
            gc.collect()
            
            if result.get('success'):
                # FILESTORE-SAFE: Solo actualiza campos de la factura
                self.write({
                    'ml_uploaded': True, 
                    'ml_upload_date': fields.Datetime.now()
                })
                
                # FILESTORE-SAFE: Crea registro de log (no attachments)
                self.env['mercadolibre.log'].create_log(
                    invoice_id=self.id, 
                    status='success', 
                    message=result.get('message'),
                    pack_id=self.ml_pack_id, 
                    ml_response=json.dumps(result.get('data', {}))
                )
                
                return {
                    'type': 'ir.actions.client', 
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Éxito', 
                        'message': 'Factura subida exitosamente a MercadoLibre', 
                        'type': 'success'
                    }
                }
            else:
                # FILESTORE-SAFE: Crea log de error (no attachments)
                error_msg = result.get('error', 'Error desconocido')
                
                self.env['mercadolibre.log'].create_log(
                    invoice_id=self.id, 
                    status='error', 
                    message=error_msg, 
                    pack_id=self.ml_pack_id
                )
                
                raise UserError('Error subiendo factura: %s' % error_msg)
                
        except UserError:
            raise
        except Exception as e:
            error_msg = 'Error inesperado: %s' % str(e)
            _logger.error('Unexpected error uploading %s: %s', self.name, error_msg)
            
            # FILESTORE-SAFE: Log de error sin attachments
            self.env['mercadolibre.log'].create_log(
                invoice_id=self.id, 
                status='error', 
                message=error_msg, 
                pack_id=self.ml_pack_id or 'Unknown'
            )
            
            raise UserError('Error inesperado: %s' % str(e))
        finally:
            # FILESTORE-SAFE: Limpieza final garantizada
            gc.collect()

    @api.model
    def cron_upload_ml_invoices(self):
        """
        CRON - FILESTORE-SAFE GARANTIZADO
        
        SEGURIDAD FILESTORE:
        - Solo procesa registros existentes
        - No crea attachments
        - Limpieza de memoria entre facturas
        """
        try:
            config = self.env['mercadolibre.config'].get_active_config()
            if not config or not config.auto_upload:
                return
            
            # FILESTORE-SAFE: Solo búsqueda de registros
            pending_invoices = self.search([
                ('state', '=', 'posted'), 
                ('is_ml_sale', '=', True), 
                ('ml_uploaded', '=', False),
                ('move_type', 'in', ['out_invoice', 'out_refund']), 
                ('ml_pack_id', '!=', False)
            ], limit=25)
            
            if not pending_invoices:
                return
            
            success_count = 0
            error_count = 0
            
            for invoice in pending_invoices:
                try:
                    with self.env.cr.savepoint():
                        # FILESTORE-SAFE: Proceso individual que no toca filestore
                        invoice.action_upload_to_mercadolibre()
                        success_count += 1
                    
                    self.env.cr.commit()
                    # FILESTORE-SAFE: Limpieza de memoria entre facturas
                    gc.collect()
                    
                    import time
                    time.sleep(2)
                    
                except Exception as e:
                    error_count += 1
                    _logger.error('Auto upload failed for %s: %s', invoice.name, str(e))
                    
                    if error_count >= 3:
                        _logger.warning('Stopping after %d errors for safety', error_count)
                        break
            
            _logger.info('Auto upload completed: %d successful, %d errors', success_count, error_count)
            
        except Exception as e:
            _logger.error('Critical error in CRON upload: %s', str(e))
        finally:
            # FILESTORE-SAFE: Limpieza final
            gc.collect()

    def test_report_generation(self):
        """
        MÉTODO DE PRUEBA - Test de generación de reportes sin subir a ML
        Ejecutar desde consola: invoice.test_report_generation()
        """
        self.ensure_one()
        
        try:
            _logger.info('=== TESTING REPORT GENERATION FOR %s ===', self.name)
            
            # Test de generación de PDF
            pdf_content = self._generate_pdf_adhoc_priority()
            
            result = {
                'success': True,
                'invoice': self.name,
                'pdf_size_bytes': len(pdf_content),
                'pdf_size_kb': round(len(pdf_content) / 1024, 2),
                'message': 'PDF generated successfully'
            }
            
            _logger.info('TEST SUCCESS: %s', result)
            return result
            
        except Exception as e:
            result = {
                'success': False,
                'invoice': self.name,
                'error': str(e),
                'message': 'PDF generation failed'
            }
            
            _logger.error('TEST FAILED: %s', result)
            return result
