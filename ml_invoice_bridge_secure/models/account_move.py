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
        """
        Context manager FILESTORE-SAFE - GARANTÍA TOTAL
        """
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

    def _generate_pdf_simple_approach(self):
        """
        🎯 ENFOQUE SIMPLE Y SEGURO
        Usa el reporte por defecto sin interferir con ADHOC
        """
        self.ensure_one()
        
        try:
            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            _logger.info('Generating legal PDF for invoice %s using correct report objects', self.name)
            
            # MÉTODO SIMPLE: Buscar reportes sin complejidad
            reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf')
            ], order='id desc')
            
            _logger.info(f'Found {len(reports)} available reports for account.move')
            
            # Probar reportes hasta encontrar uno que funcione
            for report in reports:
                try:
                    _logger.info(f'Trying report: {report.name} (ID: {report.id})')
                    
                    # Generar PDF
                    result = report._render_qweb_pdf(self.ids)
                    
                    if isinstance(result, tuple) and len(result) >= 1:
                        pdf_content = result[0]
                        if pdf_content and len(pdf_content) > 5000:
                            
                            # VALIDACIÓN SIMPLE: Solo verificar QR AFIP
                            if b'afip.gob.ar' in pdf_content:
                                _logger.info(f'✅ SUCCESS: Report {report.name} generated PDF with AFIP QR ({len(pdf_content)} bytes)')
                                _logger.info('The PDF report has been generated for model: account.move, records %s', self.ids)
                                return pdf_content
                            else:
                                _logger.info(f'Report {report.name} generated PDF but without AFIP QR - trying next')
                                continue
                        else:
                            _logger.debug(f'Report {report.name} generated small PDF - trying next')
                            continue
                            
                except Exception as e:
                    _logger.debug(f'Report {report.name} failed: {str(e)} - trying next')
                    continue
            
            # Si ningún reporte tiene QR, error claro
            error_msg = (
                f'No se pudo generar PDF con QR de AFIP para la factura {self.name}.\n'
                'Verifique que la localización argentina esté configurada correctamente.'
            )
            _logger.error(error_msg)
            raise UserError(error_msg)
            
        except UserError:
            raise
        except Exception as e:
            error_msg = f'Error generando PDF para {self.name}: {str(e)}'
            _logger.error(error_msg)
            raise UserError(error_msg)

    def _upload_to_ml_api(self, pack_id, pdf_content, access_token):
        """
        Upload a MercadoLibre - FILESTORE-SAFE GARANTIZADO
        """
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
        """
        🎯 ACCIÓN PRINCIPAL SIMPLIFICADA Y SEGURA
        """
        self.ensure_one()
        
        try:
            # Validaciones básicas
            if not self.is_ml_sale:
                raise UserError('Esta factura no es de MercadoLibre')
            if self.ml_uploaded:
                raise UserError('Factura ya subida a MercadoLibre')
            if self.state != 'posted':
                raise UserError('Solo se pueden subir facturas validadas')
            if not self.ml_pack_id:
                raise UserError('Pack ID de MercadoLibre no encontrado')

            # Configuración
            config = self.env['mercadolibre.config'].get_active_config()
            if not config:
                raise UserError('No hay configuración de MercadoLibre activa')
            if not config.access_token:
                raise UserError('Token de acceso no configurado')

            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            
            # Generar PDF de forma simple
            pdf_content = self._generate_pdf_simple_approach()
            
            # Upload
            result = self._upload_to_ml_api(self.ml_pack_id, pdf_content, config.access_token)

            # Limpieza
            pdf_content = None
            gc.collect()

            if result.get('success'):
                # Marcar como subido
                self.write({
                    'ml_uploaded': True,
                    'ml_upload_date': fields.Datetime.now()
                })
                
                # Log de éxito
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
                        'title': '✅ Éxito',
                        'message': 'Factura subida exitosamente a MercadoLibre',
                        'type': 'success'
                    }
                }
            else:
                # Error en upload
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
        """
        CRON simplificado
        """
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
                _logger.info('No hay facturas pendientes para subir a MercadoLibre')
                return

            _logger.info(f'Procesando {len(pending_invoices)} facturas pendientes para MercadoLibre')

            success_count = 0
            error_count = 0

            for invoice in pending_invoices:
                try:
                    with self.env.cr.savepoint():
                        invoice.action_upload_to_mercadolibre()
                        success_count += 1
                        _logger.info(f'✅ Factura {invoice.name} subida exitosamente')
                    
                    self.env.cr.commit()
                    gc.collect()
                    time.sleep(2)
                    
                except Exception as e:
                    error_count += 1
                    _logger.error('❌ Auto upload falló para %s: %s', invoice.name, str(e))
                    
                    if error_count >= 3:
                        _logger.warning('🛑 Deteniendo después de %d errores por seguridad', error_count)
                        break

            _logger.info(f'📊 Auto upload completado: {success_count} exitosos, {error_count} errores')

        except Exception as e:
            _logger.error('🚨 Error crítico en CRON de subida: %s', str(e))
        finally:
            gc.collect()

    def test_report_generation(self):
        """
        🧪 MÉTODO DE PRUEBA SIMPLE
        """
        self.ensure_one()
        
        try:
            _logger.info('=== TESTING SIMPLE REPORT GENERATION FOR %s ===', self.name)
            
            pdf_content = self._generate_pdf_simple_approach()
            
            # Verificación básica
            has_qr = b'afip.gob.ar' in pdf_content
            
            result = {
                'success': True,
                'invoice': self.name,
                'pdf_size_bytes': len(pdf_content),
                'pdf_size_kb': round(len(pdf_content) / 1024, 2),
                'has_afip_qr': has_qr,
                'message': '✅ PDF generado exitosamente' + (' con QR AFIP' if has_qr else ' sin QR AFIP'),
                'validation': 'PASSED' if has_qr else 'WARNING - NO QR'
            }
            
            _logger.info('✅ TEST SUCCESS: %s', result)
            return result
            
        except Exception as e:
            result = {
                'success': False,
                'invoice': self.name,
                'error': str(e),
                'has_afip_qr': False,
                'message': '❌ Falló generación de PDF',
                'validation': 'FAILED'
            }
            
            _logger.error('❌ TEST FAILED: %s', result)
            return result
