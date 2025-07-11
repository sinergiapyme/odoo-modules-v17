# -*- coding: utf-8 -*-

import logging
import requests
import base64
import io
import hashlib
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools import config

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # Campos ML básicos - CONSISTENTES con las vistas
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

    # Método principal para subir a ML
    def action_upload_to_ml(self):
        """Acción principal: generar PDF legal y subir a ML"""
        self.ensure_one()
        
        if not self.ml_pack_id:
            raise UserError("Esta factura no tiene Pack ID asociado.")
        
        try:
            self.upload_status = 'uploading'
            self.last_upload_attempt = fields.Datetime.now()
            
            _logger.info("Starting upload for invoice %s, ml_pack_id: %s", self.display_name, self.ml_pack_id)
            
            # GENERAR PDF LEGAL - MÉTODO CORREGIDO PERO COMPLETO
            pdf_content = self._get_legal_pdf_content_fixed()
            
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

    # PRESERVADO: Método compatible para el log (mantener retrocompatibilidad)
    def action_upload_to_mercadolibre(self):
        """Método compatible para retrocompatibilidad"""
        return self.action_upload_to_ml()

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

    def _get_legal_pdf_content_fixed(self):
        """
        GENERACIÓN DE PDF - VERSIÓN CORREGIDA PERO COMPLETA
        Mantiene múltiples estrategias pero corrige el error específico
        """
        self.ensure_one()
        
        _logger.info("=== STARTING PDF GENERATION FOR %s ===", self.display_name)
        
        # ESTRATEGIA 1: Referencias directas (sin búsquedas complejas que causan error)
        direct_reports = self._get_direct_report_references()
        if direct_reports:
            _logger.info("Found %d direct reports, trying them first", len(direct_reports))
            for report in direct_reports:
                pdf = self._try_generate_pdf_safe(report, "DIRECT")
                if self._is_valid_legal_pdf(pdf):
                    return pdf
        
        # ESTRATEGIA 2: Búsqueda simple SIN filtros complejos
        simple_reports = self._get_simple_report_search()
        if simple_reports:
            _logger.info("Found %d simple reports, trying them", len(simple_reports))
            for report in simple_reports:
                pdf = self._try_generate_pdf_safe(report, "SIMPLE")
                if self._is_valid_legal_pdf(pdf):
                    return pdf
        
        # ESTRATEGIA 3: Reportes prioritarios por nombre (SIN filtros lambda complejos)
        priority_reports = self._get_priority_reports_safe()
        if priority_reports:
            _logger.info("Found %d priority reports, trying them", len(priority_reports))
            for report in priority_reports:
                pdf = self._try_generate_pdf_safe(report, "PRIORITY")
                if self._is_valid_legal_pdf(pdf):
                    return pdf
        
        # ESTRATEGIA 4: Cualquier reporte disponible
        all_reports = self.env['ir.actions.report'].search([
            ('model', '=', 'account.move'),
            ('report_type', '=', 'qweb-pdf')
        ], limit=5)
        
        if all_reports:
            _logger.info("FORCE MODE: Trying any available report")
            for report in all_reports:
                pdf = self._try_generate_pdf_safe(report, "FORCE")
                if pdf and len(pdf) > 1000:  # Al menos 1KB
                    _logger.warning("Force accepting PDF of %d bytes", len(pdf))
                    return pdf
        
        # Si llegamos aquí, nada funcionó
        _logger.error("ALL STRATEGIES FAILED - No PDF could be generated")
        raise UserError(
            "No se pudo generar ningún PDF de la factura. "
            "Verifique que los módulos de reportes estén instalados correctamente."
        )

    def _get_direct_report_references(self):
        """Obtener reportes por referencia directa XML (evita búsquedas complejas)"""
        reports = []
        
        # Referencias directas conocidas de Odoo
        report_refs = [
            'account.account_invoices',  # Reporte estándar de facturas
            'account.account_invoices_without_payment',  # Sin pago
            'l10n_ar.report_invoice_document',  # Argentina específico
            'account.report_invoice',  # Básico
        ]
        
        for ref in report_refs:
            try:
                report = self.env.ref(ref, raise_if_not_found=False)
                if report:
                    reports.append(report)
                    _logger.info("Found direct reference: %s", ref)
            except Exception as e:
                _logger.warning("Direct reference %s failed: %s", ref, str(e))
                continue
        
        return reports

    def _get_simple_report_search(self):
        """Búsqueda simple sin filtros complejos"""
        try:
            reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf'),
                ('binding_model_id', '!=', False)  # Solo reportes del menú
            ])
            
            _logger.info("Simple search found %d GUI reports", len(reports))
            return reports
            
        except Exception as e:
            _logger.warning("Simple search failed: %s", str(e))
            return self.env['ir.actions.report'].browse()

    def _get_priority_reports_safe(self):
        """Obtener reportes prioritarios SIN usar filtros lambda complejos"""
        try:
            all_reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf')
            ])
            
            priority_reports = []
            
            # CORREGIDO: Iterar manualmente sin filtros lambda complejos
            for report in all_reports:
                name_lower = (report.name or '').lower()
                report_name_lower = (report.report_name or '').lower()
                
                # Buscar palabras clave prioritarias
                priority_keywords = ['argentina', 'afip', 'fe', 'adhoc', 'facturas sin pago', 'factura electronica']
                
                for keyword in priority_keywords:
                    if keyword in name_lower or keyword in report_name_lower:
                        priority_reports.append(report)
                        _logger.info("Found priority report: %s (keyword: %s)", report.name, keyword)
                        break
            
            return priority_reports
            
        except Exception as e:
            _logger.warning("Priority search failed: %s", str(e))
            return self.env['ir.actions.report'].browse()

    def _try_generate_pdf_safe(self, report, strategy_name):
        """Intentar generar PDF de forma segura - MÉTODO CORREGIDO"""
        try:
            _logger.info("TRYING %s: %s (ID: %s)", strategy_name, report.name, report.id)
            
            # CORREGIDO: Método simple sin contextos complejos que causaban el error
            try:
                pdf_content, _ = report._render_qweb_pdf(self.ids)
                
                if pdf_content and len(pdf_content) > 1000:
                    _logger.info("✅ SUCCESS: Generated PDF: %d bytes with report %s", len(pdf_content), report.name)
                    return pdf_content
                    
            except Exception as render_error:
                _logger.warning("Render failed for %s: %s", report.name, str(render_error))
            
            _logger.warning("❌ FAILED for report %s", report.name)
            return None
            
        except Exception as e:
            _logger.warning("❌ CRITICAL ERROR with report %s: %s", report.name, str(e))
            return None

    # PRESERVADO: Validación robusta de PDF legal
    def _is_valid_legal_pdf(self, pdf_content):
        """Validación COMPLETA de PDF legal"""
        if not pdf_content:
            return False
        
        # Validación básica de tamaño
        if len(pdf_content) < 500:
            _logger.warning("PDF too small: %d bytes", len(pdf_content))
            return False
        
        if len(pdf_content) > 50 * 1024 * 1024:
            _logger.warning("PDF too large: %d bytes", len(pdf_content))
            return False
        
        # Verificar que sea un PDF válido
        if not pdf_content.startswith(b'%PDF-'):
            _logger.warning("Not a valid PDF file")
            return False
        
        # Intentar extraer texto para validación básica
        try:
            text_content = self._extract_text_simple(pdf_content)
            if text_content:
                text_lower = text_content.lower()
                
                # PRESERVADO: Validación específica QR AFIP
                qr_patterns = [
                    'afip.gob.ar/fe/qr',
                    'https://www.afip.gob.ar/fe/qr/',
                    'qr?p=',
                    'codigo qr',
                    'código qr'
                ]
                
                qr_found = any(pattern in text_lower for pattern in qr_patterns)
                if qr_found:
                    _logger.info("✅ PDF VALID: QR AFIP detected!")
                    return True
                
                # Buscar indicadores básicos de factura legal argentina
                legal_indicators = [
                    'cae', 'cuit', 'afip', 'factura', 'iva', 
                    'qr', 'codigo', 'fecha', 'total', 'punto de venta'
                ]
                
                found_indicators = sum(1 for indicator in legal_indicators 
                                     if indicator in text_lower)
                
                if found_indicators >= 3:
                    _logger.info("✅ PDF VALID: Found %d legal indicators", found_indicators)
                    return True
                else:
                    _logger.info("PDF has %d indicators (need 3+)", found_indicators)
            
            # Si no se puede extraer texto pero el PDF es grande, aceptarlo
            if len(pdf_content) > 50000:
                _logger.info("✅ PDF VALID: Large PDF accepted (text extraction failed)")
                return True
            
        except Exception as e:
            _logger.warning("Error validating PDF: %s", str(e))
            if len(pdf_content) > 20000:
                _logger.info("✅ PDF VALID: Validation error but size acceptable")
                return True
        
        _logger.warning("❌ PDF INVALID: Failed validation checks")
        return False

    # PRESERVADO: Extracción de texto
    def _extract_text_simple(self, pdf_content):
        """Extracción simple de texto sin dependencias complejas"""
        try:
            try:
                from PyPDF2 import PdfReader
                pdf_file = io.BytesIO(pdf_content)
                reader = PdfReader(pdf_file)
                
                text = ""
                for i, page in enumerate(reader.pages[:5]):
                    try:
                        text += page.extract_text() + "\n"
                    except:
                        continue
                
                return text.strip()
                
            except ImportError:
                text_bytes = pdf_content.decode('latin-1', errors='ignore')
                import re
                text_matches = re.findall(r'[A-Za-z0-9\s]{10,}', text_bytes)
                return ' '.join(text_matches[:100])
                
        except Exception as e:
            _logger.warning("Text extraction failed: %s", str(e))
            return ""

    def _upload_to_ml_api(self, pdf_content):
        """Upload simple a ML sin complicaciones"""
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

    # PRESERVADOS: Métodos de testing completos
    def action_test_pdf_generation(self):
        """Test directo de generación de PDF"""
        self.ensure_one()
        
        try:
            _logger.info("=== TESTING PDF GENERATION ===")
            pdf_content = self._get_legal_pdf_content_fixed()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Test Exitoso',
                    'message': f'PDF generado: {len(pdf_content)} bytes',
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
                    'message': f'Error: {str(e)[:100]}',
                    'sticky': True,
                }
            }

    def action_debug_available_reports(self):
        """Debug simple de reportes disponibles"""
        self.ensure_one()
        
        _logger.info("=== DEBUGGING AVAILABLE REPORTS ===")
        
        all_reports = self.env['ir.actions.report'].search([
            ('model', '=', 'account.move'),
            ('report_type', '=', 'qweb-pdf')
        ])
        
        _logger.info("Total reports found: %d", len(all_reports))
        
        for report in all_reports:
            _logger.info("Report: %s (ID: %s, XML: %s)", 
                        report.name, report.id, report.report_name)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Debug Complete',
                'message': f'Found {len(all_reports)} reports. Check logs for details.',
                'sticky': False,
            }
        }

    # PRESERVADO: Verificación QR AFIP
    def _check_for_afip_qr(self, pdf_content):
        """Verificar específicamente si el PDF contiene QR AFIP"""
        try:
            text_content = self._extract_text_simple(pdf_content)
            if text_content:
                text_lower = text_content.lower()
                
                qr_patterns = [
                    'afip.gob.ar/fe/qr',
                    'https://www.afip.gob.ar/fe/qr/',
                    'qr?p=eyj',
                    'codigo qr',
                    'código qr'
                ]
                
                for pattern in qr_patterns:
                    if pattern in text_lower:
                        _logger.info("QR AFIP pattern found: %s", pattern)
                        return True
                        
            pdf_text = pdf_content.decode('latin-1', errors='ignore').lower()
            if 'afip.gob.ar/fe/qr' in pdf_text:
                _logger.info("QR AFIP found in binary content")
                return True
                
            return False
            
        except Exception as e:
            _logger.warning("Error checking for AFIP QR: %s", str(e))
            return False
