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
        """Context manager FILESTORE-SAFE - SIN CAMBIOS"""
        temp_file = None
        temp_path = None
        try:
            temp_file = tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False)
            temp_path = temp_file.name
            temp_file.write(data)
            temp_file.flush()
            temp_file.close()
            yield temp_path
        except Exception as e:
            _logger.error('Error creating temp file: %s', str(e))
            raise
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _generate_html_invoice(self):
        """Genera HTML básico - EXACTAMENTE IGUAL que funciona actualmente"""
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
        """Convierte HTML a PDF - EXACTAMENTE IGUAL que funciona actualmente"""
        try:
            import subprocess
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as html_file:
                html_file.write(html_content)
                html_file.flush()
                html_path = html_file.name
            
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
                    with open(pdf_path, 'rb') as pdf_file:
                        pdf_content = pdf_file.read()
                    
                    _logger.info('PDF generated with wkhtmltopdf, size: %d bytes', len(pdf_content))
                    return pdf_content
                else:
                    _logger.error('wkhtmltopdf failed: %s', result.stderr)
                    return None
                    
            finally:
                try:
                    os.unlink(html_path)
                    if os.path.exists(pdf_path):
                        os.unlink(pdf_path)
                except OSError:
                    pass
                    
        except Exception as e:
            _logger.error('Error in wkhtmltopdf conversion: %s', str(e))
            return None

    def _generate_pdf_adhoc_priority(self):
        """
        ÚNICO CAMBIO: Intenta reportes ADHOC ANTES del fallback HTML
        SEGURIDAD: Mantiene el mismo fallback que ya funciona
        """
        try:
            _logger.info('Generating PDF for invoice %s with ADHOC priority', self.name)
            
            # IDs corruptos conocidos que debemos evitar (ya identificados antes)
            corrupted_report_ids = [213, 214, 215]
            
            # PASO 1: Intentar reportes ADHOC Argentina específicos
            try:
                _logger.info('Trying ADHOC Argentina reports')
                
                adhoc_report_refs = [
                    'l10n_ar.report_invoice',
                    'l10n_ar_reports.action_report_invoice_electronic', 
                    'l10n_ar.action_report_invoice'
                ]
                
                for report_ref in adhoc_report_refs:
                    try:
                        report = self.env.ref(report_ref, raise_if_not_found=False)
                        if report and hasattr(report, '_render_qweb_pdf'):
                            # Verificar que no sea corrupto
                            if hasattr(report, 'id') and report.id in corrupted_report_ids:
                                _logger.info('Skipping corrupted ADHOC report ID: %d', report.id)
                                continue
                            
                            _logger.info('Trying ADHOC report: %s (ID: %d)', report_ref, getattr(report, 'id', 0))
                            
                            result = report._render_qweb_pdf(self.ids)
                            if isinstance(result, tuple) and len(result) >= 1:
                                pdf_content = result[0]
                                if pdf_content and len(pdf_content) > 5000:  # ADHOC debe ser >5KB
                                    _logger.info('SUCCESS: ADHOC PDF generated (%d bytes) with: %s', len(pdf_content), report_ref)
                                    return pdf_content
                                    
                    except Exception as e:
                        _logger.info('ADHOC report %s failed: %s', report_ref, str(e))
                        continue
                        
            except Exception as e:
                _logger.info('ADHOC search failed: %s', str(e))
            
            # PASO 2: Buscar otros reportes Argentina no corruptos
            try:
                _logger.info('Trying other Argentina reports')
                
                all_reports = self.env['ir.actions.report'].search([
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf'),
                    ('id', 'not in', corrupted_report_ids)
                ])
                
                # Filtrar reportes que pueden ser de Argentina
                argentina_reports = all_reports.filtered(
                    lambda r: any(keyword in r.report_name.lower() 
                                for keyword in ['ar', 'argentina', 'l10n_ar', 'adhoc'])
                )
                
                _logger.info('Found %d potential Argentina reports', len(argentina_reports))
                
                for report in argentina_reports:
                    try:
                        _logger.info('Trying Argentina report ID: %d, name: %s', report.id, report.report_name)
                        
                        result = report._render_qweb_pdf(self.ids)
                        if isinstance(result, tuple) and len(result) >= 1:
                            pdf_content = result[0]
                            if pdf_content and len(pdf_content) > 5000:
                                _logger.info('SUCCESS: Argentina PDF generated (%d bytes) with ID: %d', len(pdf_content), report.id)
                                return pdf_content
                                
                    except Exception as e:
                        _logger.info('Argentina report %d failed: %s', report.id, str(e))
                        continue
                        
            except Exception as e:
                _logger.info('Argentina reports search failed: %s', str(e))
            
            # PASO 3: FALLBACK - Usar el método HTML que YA FUNCIONA
            _logger.info('ADHOC reports not available, using proven HTML fallback')
            
            try:
                html_content = self._generate_html_invoice()
                pdf_content = self._html_to_pdf_wkhtmltopdf(html_content)
                
                if pdf_content and len(pdf_content) > 100:
                    _logger.info('FALLBACK: HTML PDF generated successfully (%d bytes)', len(pdf_content))
                    return pdf_content
                    
            except Exception as e:
                _logger.error('Even HTML fallback failed: %s', str(e))
            
            # Si TODO falla (muy improbable)
            raise UserError('No se pudo generar PDF.\n'
                          'Contacte al administrador del sistema.')
            
        except UserError:
            raise
        except Exception as e:
            error_msg = 'Error generating PDF for %s: %s' % (self.name, str(e))
            _logger.error(error_msg)
            raise UserError('Error generando PDF: %s' % str(e))

    def _upload_to_ml_api(self, pack_id, pdf_content, access_token):
        """Upload a MercadoLibre - SIN CAMBIOS (ya funciona perfectamente)"""
        try:
            url = 'https://api.mercadolibre.com/packs/%s/fiscal_documents' % pack_id
            headers = {'Authorization': 'Bearer %s' % access_token}
            
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
        """Acción principal - CAMBIO MÍNIMO (solo método PDF)"""
        self.ensure_one()
        
        try:
            # Validaciones - SIN CAMBIOS
            if not self.is_ml_sale:
                raise UserError('Esta factura no es de MercadoLibre')
            if self.ml_uploaded:
                raise UserError('Factura ya subida a MercadoLibre')
            if self.state != 'posted':
                raise UserError('Solo se pueden subir facturas validadas')
            if not self.ml_pack_id:
                raise UserError('Pack ID de MercadoLibre no encontrado')
            
            # Configuración - SIN CAMBIOS
            config = self.env['mercadolibre.config'].get_active_config()
            if not config:
                raise UserError('No hay configuración de MercadoLibre activa')
            if not config.access_token:
                raise UserError('Token de acceso no configurado')
            
            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            
            # ÚNICO CAMBIO: Método específico para el reporte correcto
            pdf_content = self._generate_pdf_targeted_report()
            
            # Upload - SIN CAMBIOS
            result = self._upload_to_ml_api(self.ml_pack_id, pdf_content, config.access_token)
            
            # Limpieza - SIN CAMBIOS
            pdf_content = None
            gc.collect()
            
            if result.get('success'):
                # Éxito - SIN CAMBIOS
                self.write({
                    'ml_uploaded': True, 
                    'ml_upload_date': fields.Datetime.now()
                })
                
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
                # Error - SIN CAMBIOS
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
            
            self.env['mercadolibre.log'].create_log(
                invoice_id=self.id, 
                status='error', 
                message=error_msg, 
                pack_id=self.ml_pack_id or 'Unknown'
            )
            
            raise UserError('Error inesperado: %s' % str(e))
        finally:
            gc.collect()

    @api.model
    def cron_upload_ml_invoices(self):
        """CRON - SIN CAMBIOS (ya estable y funcional)"""
        try:
            config = self.env['mercadolibre.config'].get_active_config()
            if not config or not config.auto_upload:
                return
            
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
                        invoice.action_upload_to_mercadolibre()
                        success_count += 1
                    
                    self.env.cr.commit()
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
            gc.collect()
