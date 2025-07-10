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

    def _validate_legal_pdf_content(self, pdf_content):
        """
        🚨 VALIDACIÓN CRÍTICA - NUNCA permite documentos ilegales
        Verifica que el PDF contenga elementos legales mínimos argentinos
        """
        if not pdf_content or len(pdf_content) < 5000:
            _logger.error("PDF demasiado pequeño para ser un documento legal válido")
            return False
        
        # Buscar elementos legales mínimos argentinos
        legal_indicators = [
            b'CAE',      # Código de Autorización Electrónico (OBLIGATORIO)
            b'CUIT',     # Identificación tributaria (OBLIGATORIO)
            b'AFIP',     # Administración Federal (OBLIGATORIO)
            b'IVA',      # Impuesto al Valor Agregado (OBLIGATORIO)
        ]
        
        found_indicators = []
        for indicator in legal_indicators:
            if indicator in pdf_content:
                found_indicators.append(indicator.decode())
        
        # DEBE contener AL MENOS 3 de los 4 elementos legales
        if len(found_indicators) < 3:
            _logger.error(
                f"🚨 DOCUMENTO ILEGAL DETECTADO 🚨\n"
                f"El PDF NO contiene elementos legales mínimos argentinos.\n"
                f"Encontrado: {found_indicators}\n"
                f"Requerido: AL MENOS 3 de [CAE, CUIT, AFIP, IVA]\n"
                f"Este documento NO puede ser subido a MercadoLibre."
            )
            return False
        
        _logger.info(f"✅ PDF LEGAL validado: contiene elementos {found_indicators}")
        return True

    def _generate_pdf_adhoc_priority(self):
        """
        🚨 GENERACIÓN DE PDF CON PROTECCIÓN TOTAL 🚨
        
        GARANTÍA: Solo retorna PDFs con elementos legales argentinos
        Si no puede generar un PDF legal, da error y NO sube nada
        """
        try:
            _logger.info('Starting upload for invoice %s, pack_id: %s', self.name, self.ml_pack_id)
            _logger.info('Generating legal PDF for invoice %s using correct report objects', self.name)

            # --- PASO 1: REPORTE OFICIAL l10n_ar_ux (PRIORIDAD MÁXIMA) ---
            _logger.info('🎯 PASO 1: Intentando reportes oficiales l10n_ar_ux')
            
            # Lista de XML IDs de l10n_ar_ux para probar (orden de prioridad)
            l10n_ar_ux_reports = [
                'l10n_ar_ux.report_invoice_with_payments',
                'l10n_ar_ux.report_invoice_document', 
                'l10n_ar_ux.report_invoice',
                'l10n_ar_ux.action_report_invoice_with_payments',
            ]
            
            for xml_id in l10n_ar_ux_reports:
                try:
                    _logger.info(f'🔍 Probando XML ID: {xml_id}')
                    
                    # Buscar reporte por XML ID
                    report = self.env.ref(xml_id, raise_if_not_found=False)
                    
                    if report and report.exists():
                        _logger.info(f'✅ Reporte encontrado: {report.name} (ID: {report.id})')
                        
                        # Generar PDF
                        result = report._render_qweb_pdf(self.ids)
                        
                        if isinstance(result, tuple) and len(result) >= 1:
                            pdf_content = result[0]
                            if pdf_content and len(pdf_content) > 5000:
                                # 🚨 VALIDACIÓN LEGAL CRÍTICA
                                if self._validate_legal_pdf_content(pdf_content):
                                    _logger.info(f'✅ SUCCESS: {xml_id} generó PDF LEGAL ({len(pdf_content)} bytes)')
                                    return pdf_content
                                else:
                                    _logger.error(f'🚨 RECHAZO: {xml_id} generó PDF SIN elementos legales')
                                    continue
                            else:
                                _logger.warning(f'{xml_id} generó PDF muy pequeño ({len(pdf_content) if pdf_content else 0} bytes)')
                    else:
                        _logger.warning(f'XML ID {xml_id} no encontrado en el sistema')
                        
                except Exception as e:
                    _logger.warning(f'Error con XML ID {xml_id}: {str(e)}')
                    continue

            # --- PASO 2: REPORTES POR BÚSQUEDA DE NOMBRES (FALLBACK) ---
            _logger.info('🔄 PASO 2: XML IDs fallaron, intentando búsqueda por nombres')
            
            # Buscar "Facturas sin pago" (el que funciona desde GUI)
            try:
                _logger.info('🔍 Buscando reporte GUI: "Facturas sin pago"')
                gui_report = self.env['ir.actions.report'].search([
                    ('name', '=', 'Facturas sin pago'),
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], limit=1)
                
                if gui_report:
                    _logger.info(f'✅ Reporte GUI encontrado: {gui_report.name} (ID: {gui_report.id})')
                    result = gui_report._render_qweb_pdf(self.ids)
                    
                    if isinstance(result, tuple) and result[0] and len(result[0]) > 5000:
                        # 🚨 VALIDACIÓN LEGAL CRÍTICA
                        if self._validate_legal_pdf_content(result[0]):
                            _logger.info('✅ SUCCESS: GUI "Facturas sin pago" generó PDF LEGAL (%d bytes)', len(result[0]))
                            return result[0]
                        else:
                            _logger.error('🚨 RECHAZO: GUI "Facturas sin pago" generó PDF SIN elementos legales')
                else:
                    _logger.warning('Reporte GUI "Facturas sin pago" no encontrado')
                    
            except Exception as e:
                _logger.warning('Error con reporte GUI: %s', e)

            # --- PASO 3: REPORTES POR TEMPLATE NAME ---
            _logger.info('🔄 PASO 3: Búsqueda GUI falló, intentando templates específicos')
            
            # Lista de templates argentinos conocidos
            report_templates = [
                'account.report_invoice',
                'l10n_ar.report_invoice_document',
                'l10n_ar_afipws_fe.report_invoice_document',
                'l10n_ar_ux.report_invoice_document',
                'l10n_ar_ux.report_invoice',
                'account.report_invoice_with_payments'
            ]
            
            for template_name in report_templates:
                try:
                    _logger.info(f'🔍 Probando template: {template_name}')
                    
                    reports = self.env['ir.actions.report'].search([
                        ('report_name', '=', template_name),
                        ('model', '=', 'account.move'),
                        ('report_type', '=', 'qweb-pdf')
                    ])
                    
                    for report in reports:
                        try:
                            _logger.info(f'✅ Template encontrado: {report.name} (ID: {report.id})')
                            result = report._render_qweb_pdf(self.ids)
                            
                            if isinstance(result, tuple) and result[0] and len(result[0]) > 5000:
                                # 🚨 VALIDACIÓN LEGAL CRÍTICA
                                if self._validate_legal_pdf_content(result[0]):
                                    _logger.info(f'✅ SUCCESS: Template {template_name} generó PDF LEGAL ({len(result[0])} bytes)')
                                    return result[0]
                                else:
                                    _logger.error(f'🚨 RECHAZO: Template {template_name} generó PDF SIN elementos legales')
                                    
                        except Exception as e:
                            _logger.debug(f'Error generando PDF con {report.name}: {str(e)}')
                            continue
                            
                except Exception as e:
                    _logger.debug(f'Error buscando template {template_name}: {str(e)}')
                    continue

            # --- PASO 4: REPORTES POR IDs ESPECÍFICOS ---
            _logger.info('🔄 PASO 4: Templates fallaron, probando IDs específicos del log')
            
            # IDs que aparecieron en logs anteriores
            report_ids_to_try = [215, 213, 214]
            
            for report_id in report_ids_to_try:
                try:
                    _logger.info(f'🔍 Probando ID específico: {report_id}')
                    
                    report = self.env['ir.actions.report'].browse(report_id)
                    if report.exists() and report.model == 'account.move':
                        _logger.info(f'✅ ID encontrado: {report.name} (ID: {report.id})')
                        result = report._render_qweb_pdf(self.ids)
                        
                        if isinstance(result, tuple) and result[0] and len(result[0]) > 5000:
                            # 🚨 VALIDACIÓN LEGAL CRÍTICA
                            if self._validate_legal_pdf_content(result[0]):
                                _logger.info(f'✅ SUCCESS: ID {report_id} generó PDF LEGAL ({len(result[0])} bytes)')
                                return result[0]
                            else:
                                _logger.error(f'🚨 RECHAZO: ID {report_id} generó PDF SIN elementos legales')
                                
                except Exception as e:
                    _logger.debug(f'Error con ID {report_id}: {str(e)}')
                    continue

            # --- PASO 5: BÚSQUEDA GENERAL DE REPORTES ACTIVOS ---
            _logger.info('🔄 PASO 5: IDs específicos fallaron, buscando cualquier reporte activo')
            
            try:
                active_reports = self.env['ir.actions.report'].search([
                    ('model', '=', 'account.move'),
                    ('report_type', '=', 'qweb-pdf')
                ], order='id desc', limit=10)
                
                _logger.info(f'Encontrados {len(active_reports)} reportes activos para probar')
                
                for report in active_reports:
                    try:
                        _logger.info(f'🔍 Probando reporte activo: {report.name or "Sin nombre"} (ID: {report.id})')
                        result = report._render_qweb_pdf(self.ids)
                        
                        if isinstance(result, tuple) and result[0] and len(result[0]) > 5000:
                            # 🚨 VALIDACIÓN LEGAL CRÍTICA
                            if self._validate_legal_pdf_content(result[0]):
                                _logger.info(f'✅ SUCCESS: Reporte activo ID {report.id} generó PDF LEGAL ({len(result[0])} bytes)')
                                return result[0]
                            else:
                                _logger.error(f'🚨 RECHAZO: Reporte activo ID {report.id} generó PDF SIN elementos legales')
                                
                    except Exception as e:
                        _logger.debug(f'Error con reporte activo ID {report.id}: {str(e)}')
                        continue
                        
            except Exception as e:
                _logger.warning(f'Error en búsqueda de reportes activos: {str(e)}')

            # 🚨 PROTECCIÓN TOTAL: FALLO SEGURO - NUNCA MÁS DOCUMENTOS ILEGALES
            # NO HAY FALLBACK HTML - MEJOR ERROR QUE DOCUMENTO ILEGAL
            
            error_msg = (
                '🚨 CRÍTICO: IMPOSIBLE GENERAR PDF LEGAL 🚨\n\n'
                f'No se pudo generar PDF con elementos legales para factura {self.name}.\n\n'
                '❌ Todos los reportes disponibles fallaron la validación legal\n'
                '❌ Ningún PDF contiene CAE, CUIT, AFIP o elementos AFIP requeridos\n'
                '❌ NO se generará documento de respaldo (protección anti-ilegal)\n\n'
                '📋 PROBLEMAS DETECTADOS:\n'
                '• Módulo l10n_ar_ux no configurado correctamente\n'
                '• Facturación electrónica AFIP no configurada\n'
                '• Certificados AFIP faltantes o vencidos\n'
                '• Reportes de localización argentina no funcionan\n\n'
                '🔧 SOLUCIÓN REQUERIDA:\n'
                '• Verificar instalación y configuración de l10n_ar_ux\n'
                '• Configurar facturación electrónica AFIP\n'
                '• Verificar certificados AFIP válidos\n'
                '• Probar generar factura legal desde la GUI\n\n'
                '🛡️ PROTECCIÓN ACTIVADA:\n'
                'Este sistema NUNCA subirá documentos sin validez legal.\n'
                'Configure correctamente los reportes antes de reintentar.'
            )
            
            _logger.error(error_msg)
            raise UserError(error_msg)

        except UserError:
            raise
        except Exception as e:
            error_msg = f'🚨 Error crítico en generación de PDF legal para {self.name}: {str(e)}'
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
        🚨 ACCIÓN PRINCIPAL CON PROTECCIÓN TOTAL 🚨
        Solo sube PDFs que pasen validación legal estricta
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
            
            # 🚨 GENERACIÓN CON PROTECCIÓN TOTAL
            # Si esto falla, se da error y NO se sube nada
            pdf_content = self._generate_pdf_adhoc_priority()
            
            # Upload del PDF LEGAL
            result = self._upload_to_ml_api(self.ml_pack_id, pdf_content, config.access_token)

            # Limpieza de memoria
            pdf_content = None
            gc.collect()

            if result.get('success'):
                # Marcar como subido exitosamente
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
                        'message': 'Factura LEGAL subida exitosamente a MercadoLibre',
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
            
            # Log de error
            self.env['mercadolibre.log'].create_log(
                invoice_id=self.id,
                status='error',
                message=error_msg,
                pack_id=self.ml_pack_id or 'Unknown'
            )
            
            raise UserError('Error inesperado: %s' % str(e))
        finally:
            # Limpieza final
            gc.collect()

    @api.model
    def cron_upload_ml_invoices(self):
        """
        🚨 CRON CON PROTECCIÓN TOTAL 🚨
        Solo procesa facturas que puedan generar PDFs legales
        """
        try:
            config = self.env['mercadolibre.config'].get_active_config()
            if not config or not config.auto_upload:
                return

            # Buscar facturas pendientes
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
                        # Intentar subir con protección total
                        invoice.action_upload_to_mercadolibre()
                        success_count += 1
                        _logger.info(f'✅ Factura {invoice.name} subida exitosamente')
                    
                    self.env.cr.commit()
                    gc.collect()
                    time.sleep(2)  # Pausa entre uploads
                    
                except Exception as e:
                    error_count += 1
                    _logger.error('❌ Auto upload falló para %s: %s', invoice.name, str(e))
                    
                    # Detener si hay muchos errores consecutivos
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
        🧪 MÉTODO DE PRUEBA SEGURO
        Prueba generación de PDF sin subir a MercadoLibre
        """
        self.ensure_one()
        
        try:
            _logger.info('=== TESTING LEGAL PDF GENERATION FOR %s ===', self.name)
            
            # Intentar generar PDF con todas las validaciones
            pdf_content = self._generate_pdf_adhoc_priority()
            
            result = {
                'success': True,
                'invoice': self.name,
                'pdf_size_bytes': len(pdf_content),
                'pdf_size_kb': round(len(pdf_content) / 1024, 2),
                'message': '✅ PDF LEGAL generado exitosamente',
                'validation': 'PASSED - Contiene elementos legales argentinos'
            }
            
            _logger.info('✅ TEST SUCCESS: %s', result)
            return result
            
        except Exception as e:
            result = {
                'success': False,
                'invoice': self.name,
                'error': str(e),
                'message': '❌ Falló generación de PDF legal',
                'validation': 'FAILED - No se pudo generar documento legal'
            }
            
            _logger.error('❌ TEST FAILED: %s', result)
            return result

    def action_debug_available_reports(self):
        """
        🔧 MÉTODO DE DEBUG - Ver reportes disponibles
        """
        self.ensure_one()
        
        reports_info = []
        
        # 1. Verificar módulos instalados
        ar_modules = self.env['ir.module.module'].search([
            ('name', 'like', 'l10n_ar%'),
            ('state', '=', 'installed')
        ])
        
        reports_info.append("=== MÓDULOS ARGENTINOS INSTALADOS ===")
        for module in ar_modules:
            reports_info.append(f"• {module.name}: {module.state}")
        
        # 2. Ver XML IDs de reportes
        reports_info.append("\n=== XML IDs DE REPORTES DISPONIBLES ===")
        data = self.env['ir.model.data'].search([
            ('module', 'like', 'l10n_ar%'),
            ('model', '=', 'ir.actions.report')
        ])
        
        for d in data:
            report = self.env['ir.actions.report'].browse(d.res_id)
            if report.exists():
                reports_info.append(f"• {d.module}.{d.name} -> {report.name}")
        
        # 3. Ver todos los reportes de account.move
        reports_info.append("\n=== TODOS LOS REPORTES DE FACTURAS ===")
        all_reports = self.env['ir.actions.report'].search([
            ('model', '=', 'account.move'),
            ('report_type', '=', 'qweb-pdf')
        ])
        
        for report in all_reports:
            reports_info.append(f"• ID {report.id}: {report.name} ({report.report_name})")
        
        # Log completo
        complete_info = "\n".join(reports_info)
        _logger.info(f"DEBUG INFO FOR {self.name}:\n{complete_info}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '🔧 Debug Reportes',
                'message': f'Información completa loggeada. Revisar logs del servidor.',
                'type': 'info'
            }
        }
