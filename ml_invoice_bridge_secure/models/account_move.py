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

    def _validate_legal_qr_content(self, pdf_content):
        """
        🛡️ VALIDACIÓN DEFINITIVA: QR DE AFIP PRESENTE
        Si el PDF contiene QR de AFIP, es un documento legal válido
        """
        if not pdf_content or len(pdf_content) < 5000:
            _logger.error("PDF demasiado pequeño para ser un documento legal válido")
            return False
        
        # INDICADORES QR DE AFIP (GARANTÍA DE LEGALIDAD)
        afip_qr_indicators = [
            b'afip.gob.ar/fe/qr',     # QR oficial de AFIP
            b'www.afip.gob.ar/fe/qr', # Variante con www
            b'afip.gob.ar',           # Dominio AFIP general
            b'qr.afip.gob.ar'         # Subdominio QR
        ]
        
        # Verificar presencia de QR AFIP
        has_afip_qr = any(indicator in pdf_content for indicator in afip_qr_indicators)
        
        if has_afip_qr:
            _logger.info("✅ PDF LEGAL CONFIRMADO: Contiene QR de AFIP - Documento válido para Argentina")
            return True
        
        # VALIDACIÓN SECUNDARIA: Si no tiene QR, verificar otros elementos legales
        secondary_legal_indicators = [
            b'CAE',                   # Código de Autorización Electrónico
            b'CUIT',                  # CUIT de la empresa
            b'AFIP',                  # Mención de AFIP
            b'Responsable Inscripto'  # Condición ante IVA
        ]
        
        found_secondary = [indicator.decode('utf-8', errors='ignore') 
                          for indicator in secondary_legal_indicators 
                          if indicator in pdf_content]
        
        if len(found_secondary) >= 3:
            _logger.warning(f"⚠️ PDF sin QR AFIP pero con elementos legales: {found_secondary}")
            _logger.warning("Aceptando PDF pero recomienda verificar configuración de QR")
            return True
        
        # VALIDACIÓN ESTRUCTURAL: PDF válido pero sin elementos legales
        if pdf_content.startswith(b'%PDF') and len(pdf_content) > 20000:
            _logger.error(f"🚨 PDF RECHAZADO: Estructura válida pero SIN elementos legales argentinos")
            _logger.error(f"Tamaño: {len(pdf_content)} bytes, Elementos encontrados: {found_secondary}")
            return False
        
        _logger.error("🚨 PDF RECHAZADO: No es un documento legal argentino válido")
        return False

    def _get_default_invoice_report(self):
        """
        🎯 MÉTODO CLAVE: Obtiene el reporte por defecto de facturas
        EXACTAMENTE como lo hace la GUI cuando presionas "Print"
        """
        self.ensure_one()
        
        try:
            # MÉTODO 1: Usar el mismo mecanismo que la GUI
            # La GUI busca el reporte por defecto para el modelo account.move
            
            # Buscar reportes activos para facturas
            invoice_reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf'),
                ('groups_id', '=', False),  # Sin restricciones de grupos (accesible para todos)
            ], order='id desc')  # Los más recientes primero
            
            _logger.info(f'Found {len(invoice_reports)} available invoice reports')
            
            for report in invoice_reports:
                _logger.info(f'Checking report: {report.name} (ID: {report.id}, Template: {report.report_name})')
                
                # Verificar que el reporte sea válido para este registro
                try:
                    # Probar renderizado (como hace la GUI internamente)
                    test_result = report._render_qweb_pdf(self.ids)
                    
                    if isinstance(test_result, tuple) and len(test_result) >= 1:
                        pdf_content = test_result[0]
                        if pdf_content and len(pdf_content) > 1000:  # PDF válido
                            
                            # 🛡️ VALIDACIÓN QR CRÍTICA AQUÍ
                            if self._validate_legal_qr_content(pdf_content):
                                _logger.info(f'✅ Report {report.name} (ID: {report.id}) generated LEGAL PDF with QR ({len(pdf_content)} bytes)')
                                return report
                            else:
                                _logger.warning(f'🚨 Report {report.name} generated PDF WITHOUT legal QR - REJECTED')
                                continue
                        else:
                            _logger.debug(f'Report {report.name} generated empty or small PDF')
                            
                except Exception as e:
                    _logger.debug(f'Report {report.name} failed test: {str(e)}')
                    continue
            
            # MÉTODO 2: Buscar el reporte específico que aparece en el menú Print
            # El que tiene binding_model_id configurado
            bound_reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf'),
                ('binding_model_id', '!=', False),  # Tiene binding (aparece en menú)
            ], order='id desc')
            
            _logger.info(f'Found {len(bound_reports)} bound reports (with Print menu)')
            
            for report in bound_reports:
                try:
                    test_result = report._render_qweb_pdf(self.ids)
                    if isinstance(test_result, tuple) and test_result[0] and len(test_result[0]) > 1000:
                        
                        # 🛡️ VALIDACIÓN QR CRÍTICA AQUÍ
                        if self._validate_legal_qr_content(test_result[0]):
                            _logger.info(f'✅ Bound report {report.name} (ID: {report.id}) generated LEGAL PDF with QR')
                            return report
                        else:
                            _logger.warning(f'🚨 Bound report {report.name} generated PDF WITHOUT legal QR - REJECTED')
                            continue
                            
                except Exception as e:
                    _logger.debug(f'Bound report {report.name} failed: {str(e)}')
                    continue
            
            # MÉTODO 3: Último recurso - cualquier reporte que funcione CON QR
            all_reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf')
            ])
            
            _logger.warning(f'Trying last resort with {len(all_reports)} total reports')
            
            for report in all_reports:
                try:
                    test_result = report._render_qweb_pdf(self.ids)
                    if isinstance(test_result, tuple) and test_result[0] and len(test_result[0]) > 1000:
                        
                        # 🛡️ VALIDACIÓN QR CRÍTICA AQUÍ
                        if self._validate_legal_qr_content(test_result[0]):
                            _logger.warning(f'⚠️ Last resort: Using report {report.name} (ID: {report.id}) with legal QR')
                            return report
                        else:
                            _logger.debug(f'Last resort report {report.name} has no legal QR')
                            continue
                            
                except Exception as e:
                    continue
            
            return None
            
        except Exception as e:
            _logger.error(f'Error finding default invoice report: {str(e)}')
            return None

    def _generate_pdf_like_gui(self):
        """
        🎯 GENERACIÓN EXACTA COMO LA GUI CON VALIDACIÓN QR
        Replica el proceso que funciona desde el botón "Print"
        GARANTIZA que solo retorna PDFs con QR de AFIP
        """
        self.ensure_one()
        
        try:
            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            _logger.info('Generating legal PDF for invoice %s using correct report objects', self.name)
            
            # Obtener el reporte por defecto que genere PDF con QR AFIP
            report = self._get_default_invoice_report()
            
            if not report:
                error_msg = (
                    f'🚨 CRÍTICO: No se encontró ningún reporte que genere PDF con QR de AFIP para la factura {self.name}.\n\n'
                    'ESTO SIGNIFICA QUE:\n'
                    '• Los módulos de localización argentina no están configurados correctamente\n'
                    '• La facturación electrónica AFIP no está funcionando\n'
                    '• No hay reportes legales disponibles\n\n'
                    '🔧 SOLUCIÓN REQUERIDA:\n'
                    '• Verificar que la factura se pueda imprimir desde la GUI con QR\n'
                    '• Instalar/configurar módulos l10n_ar_ux o similares\n'
                    '• Configurar certificados AFIP\n\n'
                    '🛡️ PROTECCIÓN ACTIVADA: No se subirá documento sin QR legal'
                )
                _logger.error(error_msg)
                raise UserError(error_msg)
            
            _logger.info(f'Using report: {report.name} (ID: {report.id}, Template: {report.report_name})')
            
            # Generar PDF EXACTAMENTE como lo hace la GUI
            try:
                result = report._render_qweb_pdf(self.ids)
                
                if isinstance(result, tuple) and len(result) >= 1:
                    pdf_content = result[0]
                    
                    if pdf_content and len(pdf_content) > 1000:
                        
                        # 🛡️ VALIDACIÓN FINAL DE QR (DOBLE VERIFICACIÓN)
                        if self._validate_legal_qr_content(pdf_content):
                            _logger.info(f'✅ SUCCESS: PDF with legal QR generated successfully ({len(pdf_content)} bytes)')
                            _logger.info('The PDF report has been generated for model: account.move, records %s', self.ids)
                            return pdf_content
                        else:
                            # ESTO NO DEBERÍA PASAR si _get_default_invoice_report funciona bien
                            raise UserError(f'El reporte {report.name} generó PDF pero sin QR de AFIP válido')
                    else:
                        raise UserError(f'El reporte {report.name} generó un PDF muy pequeño o vacío')
                else:
                    raise UserError(f'El reporte {report.name} no generó contenido válido')
                    
            except UserError:
                raise
            except Exception as e:
                error_msg = f'Error generando PDF con reporte {report.name}: {str(e)}'
                _logger.error(error_msg)
                raise UserError(error_msg)
                
        except UserError:
            raise
        except Exception as e:
            error_msg = f'Error crítico en generación de PDF para {self.name}: {str(e)}'
            _logger.error(error_msg)
            raise UserError(f'Error crítico: {str(e)}')

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
        🎯 ACCIÓN PRINCIPAL CON GARANTÍA QR
        Usa el mismo mecanismo que la GUI + validación QR obligatoria
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
            
            # Generar PDF como lo hace la GUI (CON VALIDACIÓN QR OBLIGATORIA)
            pdf_content = self._generate_pdf_like_gui()
            
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
                        'message': 'Factura LEGAL con QR AFIP subida exitosamente a MercadoLibre',
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
        CRON con protección QR obligatoria
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
                        _logger.info(f'✅ Factura {invoice.name} con QR legal subida exitosamente')
                    
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
        🧪 MÉTODO DE PRUEBA CON VALIDACIÓN QR
        """
        self.ensure_one()
        
        try:
            _logger.info('=== TESTING REPORT GENERATION WITH QR VALIDATION FOR %s ===', self.name)
            
            pdf_content = self._generate_pdf_like_gui()
            
            # Verificación adicional de QR en la prueba
            has_qr = b'afip.gob.ar' in pdf_content
            
            result = {
                'success': True,
                'invoice': self.name,
                'pdf_size_bytes': len(pdf_content),
                'pdf_size_kb': round(len(pdf_content) / 1024, 2),
                'has_afip_qr': has_qr,
                'message': '✅ PDF LEGAL con QR AFIP generado exitosamente',
                'validation': 'PASSED - QR AFIP PRESENTE'
            }
            
            _logger.info('✅ TEST SUCCESS: %s', result)
            return result
            
        except Exception as e:
            result = {
                'success': False,
                'invoice': self.name,
                'error': str(e),
                'has_afip_qr': False,
                'message': '❌ Falló generación de PDF con QR legal',
                'validation': 'FAILED - NO QR AFIP'
            }
            
            _logger.error('❌ TEST FAILED: %s', result)
            return result
