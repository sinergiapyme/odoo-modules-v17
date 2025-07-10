# ml_invoice_bridge_secure/models/account_move.py
# -*- coding: utf-8 -*-

import base64
import tempfile
import os
import json
import logging
import re
import requests
import gc
import time
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
        temp_file = None
        temp_path = None
        try:
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
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                    _logger.debug('FILESTORE-SAFE: Cleaned temp file: %s', temp_path)
                except OSError as e:
                    _logger.warning('FILESTORE-SAFE: Could not clean temp file %s: %s', temp_path, str(e))

    def _generate_html_invoice(self):
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
                    _logger.info('FILESTORE-SAFE: PDF generated with wkhtmltopdf, size: %d bytes', len(pdf_content))
                    return pdf_content
                else:
                    _logger.error('wkhtmltopdf failed: %s', result.stderr)
                    return None
                    
            finally:
                for path in (html_path, pdf_path):
                    if os.path.exists(path):
                        try:
                            os.unlink(path)
                            _logger.debug('FILESTORE-SAFE: Cleaned temp file %s', path)
                        except OSError:
                            pass
                    
        except Exception as e:
            _logger.error('Error in wkhtmltopdf conversion: %s', str(e))
            return None

    def _generate_pdf_adhoc_priority(self):
        """
        Genera el PDF legal argentino:
        1) Intento con QWeb oficial de l10n_ar_ux (logo, CAE, QR, leyenda AFIP).
        2) Si falla, cae a toda la lógica existente (GUI report, template, candidates, HTML fallback, etc.).
        """
        # --- Paso 1: probar el reporte oficial ADHOC ---
        report_ux = self.env.ref('l10n_ar_ux.report_invoice_with_payments', False)
        if report_ux:
            try:
                result = report_ux._render_qweb_pdf(self.ids)
                if isinstance(result, tuple) and len(result) >= 1:
                    pdf_content = result[0]
                else:
                    pdf_content = result
                if pdf_content and len(pdf_content) > 5000:
                    _logger.info('SUCCESS: l10n_ar_ux.report_invoice_with_payments generated legal PDF (%d bytes)', len(pdf_content))
                    return pdf_content
            except Exception as e:
                _logger.warning('l10n_ar_ux.report_invoice_with_payments failed for %s: %s', self.name, str(e))

        # --- Paso 2: lógica original de reportes ---
        try:
            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            _logger.info('Generating legal PDF for invoice %s using correct report objects', self.name)
            
            # MÉTODO 1: Reporte GUI "Facturas sin pago"
            try:
                _logger.info('Searching for exact GUI report: "Facturas sin pago"')
                gui_report = self.env['ir.actions.report'].search([
                    ('name', '=', 'Facturas sin pago'),
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], limit=1)
                if gui_report:
                    result = gui_report._render_qweb_pdf(self.ids)
                    if isinstance(result, tuple) and len(result) >= 1:
                        pdf_content = result[0]
                        if pdf_content and len(pdf_content) > 5000:
                            _logger.info('SUCCESS: GUI report "Facturas sin pago" generated legal PDF (%d bytes)', len(pdf_content))
                            return pdf_content
                        else:
                            _logger.warning('GUI report generated small PDF (%d bytes)', len(pdf_content) if pdf_content else 0)
                else:
                    _logger.warning('GUI report "Facturas sin pago" not found')
            except Exception as e:
                _logger.warning('GUI report "Facturas sin pago" error: %s', str(e))
            
            # MÉTODO 2: Template backup 'account.report_invoice'
            try:
                _logger.info('Searching for template: account.report_invoice')
                template_report = self.env['ir.actions.report'].search([
                    ('report_name', '=', 'account.report_invoice'),
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], limit=1)
                if template_report:
                    result = template_report._render_qweb_pdf(self.ids)
                    if isinstance(result, tuple) and len(result) >= 1:
                        pdf_content = result[0]
                        if pdf_content and len(pdf_content) > 5000:
                            _logger.info('SUCCESS: Template report_invoice generated legal PDF (%d bytes)', len(pdf_content))
                            return pdf_content
                else:
                    _logger.warning('Template account.report_invoice not found')
            except Exception as e:
                _logger.warning('Template account.report_invoice search failed: %s', str(e))
            
            # MÉTODO 3: Lista de posibles reportes
            try:
                _logger.info('Searching for any working invoice report')
                report_templates = [
                    'l10n_ar.report_invoice_document',
                    'l10n_ar_afipws_fe.report_invoice_document',
                    'l10n_ar_ux.report_invoice_document',
                    'l10n_ar_ux.report_invoice',
                    'account.report_invoice_with_payments'
                ]
                for template_name in report_templates:
                    try:
                        rpt = self.env['ir.actions.report'].search([
                            ('report_name', '=', template_name),
                            ('model', '=', 'account.move')
                        ], limit=1)
                        if rpt:
                            _logger.info('Found report: %s (template: %s)', rpt.name, template_name)
                            result = rpt._render_qweb_pdf(self.ids)
                            if isinstance(result, tuple) and len(result) >= 1:
                                pdf_content = result[0]
                                if pdf_content and len(pdf_content) > 5000:
                                    _logger.info('SUCCESS: Report %s generated legal PDF (%d bytes)', rpt.name, len(pdf_content))
                                    return pdf_content
                                else:
                                    _logger.debug('Report %s generated small PDF (%d bytes)', rpt.name, len(pdf_content) if pdf_content else 0)
                    except Exception as e:
                        _logger.debug('Report %s failed: %s', template_name, str(e))
            except Exception as e:
                _logger.warning('Report template search failed: %s', str(e))
            
            # MÉTODO 4: IDs específicos del log
            try:
                _logger.info('Trying specific report IDs from previous logs')
                report_ids_to_try = [215, 213, 214]
                for report_id in report_ids_to_try:
                    try:
                        rpt = self.env['ir.actions.report'].browse(report_id)
                        if rpt.exists() and rpt.model == 'account.move':
                            result = rpt._render_qweb_pdf(self.ids)
                            if isinstance(result, tuple) and len(result) >= 1:
                                pdf_content = result[0]
                                if pdf_content and len(pdf_content) > 5000:
                                    _logger.info('SUCCESS: Report ID %d (%s) generated legal PDF (%d bytes)', report_id, rpt.name, len(pdf_content))
                                    return pdf_content
                    except Exception as e:
                        _logger.info('Report ID %d failed: %s', report_id, str(e))
            except Exception as e:
                _logger.warning('Specific report IDs search failed: %s', str(e))
            
            # MÉTODO 5: Reportes activos recientes
            try:
                _logger.info('Searching for any active account.move reports')
                active_reports = self.env['ir.actions.report'].search([
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], order='id desc', limit=10)
                for rpt in active_reports:
                    try:
                        _logger.info('Trying active report ID: %d (%s)', rpt.id, rpt.name or 'No name')
                        result = rpt._render_qweb_pdf(self.ids)
                        if isinstance(result, tuple) and len(result) >= 1:
                            pdf_content = result[0]
                            if pdf_content and len(pdf_content) > 5000:
                                _logger.info('SUCCESS: Active report ID %d generated legal PDF (%d bytes)', rpt.id, len(pdf_content))
                                return pdf_content
                    except Exception as e:
                        _logger.debug('Active report ID %d failed: %s', rpt.id, str(e))
            except Exception as e:
                _logger.warning('Active reports search failed: %s', str(e))
            
            # MÉTODO 6: Fallback HTML
            try:
                _logger.warning('All legal PDF methods failed, using HTML fallback (FILESTORE-SAFE)')
                html_content = self._generate_html_invoice()
                pdf_content = self._html_to_pdf_wkhtmltopdf(html_content)
                if pdf_content and len(pdf_content) > 100:
                    _logger.warning('FALLBACK: HTML PDF generated (%d bytes) – NOT LEGAL COMPLIANT', len(pdf_content))
                    return pdf_content
            except Exception as e:
                _logger.error('HTML fallback failed: %s', str(e))
            
            # Si todo falla:
            error_msg = (
                'CRÍTICO: No se pudo generar PDF legal para factura %s.\n'
                'Revise configuración de reportes y permisos.' % self.name
            )
            _logger.error(error_msg)
            raise UserError(error_msg)
            
        except UserError:
            raise
        except Exception as e:
            err = 'Error crítico generando PDF para %s: %s' % (self.name, str(e))
            _logger.error(err)
            raise UserError(err)

    def _upload_to_ml_api(self, pack_id, pdf_content, access_token):
        url = f'https://api.mercadolibre.com/packs/{pack_id}/fiscal_documents'
        headers = {'Authorization': f'Bearer {access_token}'}
        try:
            with self._secure_temp_file(pdf_content) as tmp:
                with open(tmp, 'rb') as f:
                    filename = f'factura_{self.name.replace("/", "_").replace(" ", "_")}.pdf'
                    files = {'fiscal_document': (filename, f, 'application/pdf')}
                    response = requests.post(url, headers=headers, files=files, timeout=30)
            if response.status_code == 200:
                return {'success': True, 'data': response.json(), 'message': 'Upload successful'}
            elif response.status_code == 401:
                return {'success': False, 'error': 'Token expirado'}
            elif response.status_code == 404:
                return {'success': False, 'error': f'Pack ID no encontrado: {pack_id}'}
            else:
                err = response.json().get('message', response.text[:200])
                return {'success': False, 'error': f'HTTP {response.status_code}: {err}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def action_upload_to_mercadolibre(self):
        self.ensure_one()
        if not self.is_ml_sale:
            raise UserError('Esta factura no es de MercadoLibre')
        if self.ml_uploaded:
            raise UserError('Factura ya subida a MercadoLibre')
        if self.state != 'posted':
            raise UserError('Solo se pueden subir facturas validadas')
        if not self.ml_pack_id:
            raise UserError('Pack ID de MercadoLibre no encontrado')

        config = self.env['mercadolibre.config'].get_active_config()
        if not config or not config.access_token:
            raise UserError('Configuración de MercadoLibre incompleta')

        _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
        pdf_content = self._generate_pdf_adhoc_priority()
        result = self._upload_to_ml_api(self.ml_pack_id, pdf_content, config.access_token)
        gc.collect()

        if result.get('success'):
            self.write({'ml_uploaded': True, 'ml_upload_date': fields.Datetime.now()})
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
            self.env['mercadolibre.log'].create_log(
                invoice_id=self.id,
                status='error',
                message=result.get('error'),
                pack_id=self.ml_pack_id
            )
            raise UserError(f'Error subiendo factura: {result.get("error")}')

    @api.model
    def cron_upload_ml_invoices(self):
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
                self.env.cr.commit()
                gc.collect()
                time.sleep(2)
                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error('Auto upload failed for %s: %s', invoice.name, str(e))
                if error_count >= 3:
                    _logger.warning('Stopping after %d errors for safety', error_count)
                    break

        _logger.info('Auto upload completed: %d successful, %d errors', success_count, error_count)

    def test_report_generation(self):
        self.ensure_one()
        try:
            _logger.info('=== TESTING REPORT GENERATION FOR %s ===', self.name)
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
