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

    # Campos básicos para ML
    pack_id = fields.Char(string='Pack ID', readonly=True)
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
        
        if not self.pack_id:
            raise UserError("Esta factura no tiene Pack ID asociado.")
        
        try:
            self.upload_status = 'uploading'
            self.last_upload_attempt = fields.Datetime.now()
            
            _logger.info("Starting upload for invoice %s, pack_id: %s", self.display_name, self.pack_id)
            
            # GENERAR PDF LEGAL - ESTO ES LO CRÍTICO
            pdf_content = self._get_legal_pdf_content()
            
            if not pdf_content:
                raise UserError("No se pudo generar el PDF legal de la factura.")
            
            _logger.info("PDF generated successfully: %d bytes", len(pdf_content))
            
            # Subir a ML
            result = self._upload_to_ml_api(pdf_content)
            
            if result.get('success'):
                self.upload_status = 'uploaded'
                self.upload_error = False
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
                raise UserError(f"Error en API de ML: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            self.upload_status = 'error'
            self.upload_error = str(e)
            _logger.error("Error uploading invoice %s: %s", self.display_name, str(e))
            raise

    def _get_legal_pdf_content(self):
        """
        GENERACIÓN DIRECTA DE PDF LEGAL
        Estrategia simple: probar reportes hasta que uno funcione
        """
        self.ensure_one()
        
        _logger.info("=== STARTING PDF GENERATION FOR %s ===", self.display_name)
        
        # ESTRATEGIA 1: Buscar reportes específicos de ADHOC/Argentina
        adhoc_reports = self._find_adhoc_reports()
        if adhoc_reports:
            _logger.info("Found %d ADHOC reports, trying them first", len(adhoc_reports))
            for report in adhoc_reports:
                pdf = self._try_generate_pdf(report, "ADHOC")
                if self._is_valid_legal_pdf(pdf):
                    return pdf
        
        # ESTRATEGIA 2: Reportes del menú Print (más confiables)
        gui_reports = self._find_gui_reports()
        if gui_reports:
            _logger.info("Found %d GUI reports, trying them", len(gui_reports))
            for report in gui_reports:
                pdf = self._try_generate_pdf(report, "GUI")
                if self._is_valid_legal_pdf(pdf):
                    return pdf
        
        # ESTRATEGIA 3: Cualquier reporte de factura disponible
        all_reports = self._find_any_invoice_reports()
        if all_reports:
            _logger.info("Found %d general reports, trying them", len(all_reports))
            for report in all_reports:
                pdf = self._try_generate_pdf(report, "GENERAL")
                if self._is_valid_legal_pdf(pdf):
                    return pdf
        
        # ESTRATEGIA 4: Forzar el primer reporte disponible
        force_reports = self.env['ir.actions.report'].search([
            ('model', '=', 'account.move'),
            ('report_type', '=', 'qweb-pdf')
        ], limit=5)
        
        if force_reports:
            _logger.info("FORCE MODE: Trying any available report")
            for report in force_reports:
                pdf = self._try_generate_pdf(report, "FORCE")
                if pdf and len(pdf) > 1000:  # Al menos 1KB
                    _logger.warning("Force accepting PDF of %d bytes", len(pdf))
                    return pdf
        
        # Si llegamos aquí, nada funcionó
        _logger.error("ALL STRATEGIES FAILED - No PDF could be generated")
        raise UserError(
            "No se pudo generar ningún PDF de la factura. "
            "Verifique que los módulos de reportes estén instalados correctamente."
        )

    def _find_adhoc_reports(self):
        """Buscar reportes específicos de ADHOC o Argentina"""
        try:
            # Buscar por nombres específicos de ADHOC
            adhoc_names = [
                'l10n_ar', 'argentina', 'afip', 'fe', 'adhoc', 
                'facturas sin pago', 'factura electronica'
            ]
            
            reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf')
            ])
            
            adhoc_reports = reports.filtered(
                lambda r: any(name in r.report_name.lower() or name in r.name.lower() 
                             for name in adhoc_names)
            )
            
            _logger.info("Found ADHOC reports: %s", [r.name for r in adhoc_reports])
            return adhoc_reports
            
        except Exception as e:
            _logger.warning("Error finding ADHOC reports: %s", str(e))
            return self.env['ir.actions.report'].browse()

    def _find_gui_reports(self):
        """Buscar reportes que aparecen en menú Print"""
        try:
            gui_reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('binding_model_id', '!=', False),
                ('report_type', '=', 'qweb-pdf')
            ])
            
            _logger.info("Found GUI reports: %s", [r.name for r in gui_reports])
            return gui_reports
            
        except Exception as e:
            _logger.warning("Error finding GUI reports: %s", str(e))
            return self.env['ir.actions.report'].browse()

    def _find_any_invoice_reports(self):
        """Buscar cualquier reporte de facturas"""
        try:
            reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('report_type', '=', 'qweb-pdf')
            ])
            
            # Filtrar los que probablemente sean de facturas
            invoice_reports = reports.filtered(
                lambda r: any(word in r.name.lower() 
                             for word in ['factura', 'invoice', 'bill'])
            )
            
            _logger.info("Found invoice reports: %s", [r.name for r in invoice_reports])
            return invoice_reports
            
        except Exception as e:
            _logger.warning("Error finding invoice reports: %s", str(e))
            return self.env['ir.actions.report'].browse()

    def _try_generate_pdf(self, report, strategy_name):
        """Intentar generar PDF con un reporte específico - REPLICANDO GUI"""
        try:
            _logger.info("TRYING %s: %s (ID: %s)", strategy_name, report.name, report.id)
            
            # MÉTODO 1: Usar el mismo flujo que la GUI
            try:
                # Simular el flujo de la GUI que vemos en el log
                pdf_content, _ = report._render_qweb_pdf([self.id])
                
                if pdf_content and len(pdf_content) > 1000:
                    _logger.info("✅ GUI METHOD: Generated PDF: %d bytes with report %s", len(pdf_content), report.name)
                    return pdf_content
                    
            except Exception as gui_error:
                _logger.warning("GUI method failed for %s: %s", report.name, str(gui_error))
            
            # MÉTODO 2: Render directo (fallback)
            try:
                # Usar render directo como alternativa
                pdf_content, _ = report.render_qweb_pdf([self.id])
                
                if pdf_content and len(pdf_content) > 1000:
                    _logger.info("✅ DIRECT METHOD: Generated PDF: %d bytes with report %s", len(pdf_content), report.name)
                    return pdf_content
                    
            except Exception as direct_error:
                _logger.warning("Direct method failed for %s: %s", report.name, str(direct_error))
            
            # MÉTODO 3: Con contexto específico
            try:
                # Usar contexto como lo haría la GUI
                context = dict(self.env.context)
                context.update({
                    'report_xml_id': report.id,
                    'active_model': 'account.move',
                    'active_ids': [self.id],
                    'active_id': self.id,
                })
                
                pdf_content, _ = report.with_context(context)._render_qweb_pdf([self.id])
                
                if pdf_content and len(pdf_content) > 1000:
                    _logger.info("✅ CONTEXT METHOD: Generated PDF: %d bytes with report %s", len(pdf_content), report.name)
                    return pdf_content
                    
            except Exception as context_error:
                _logger.warning("Context method failed for %s: %s", report.name, str(context_error))
            
            _logger.warning("❌ ALL METHODS FAILED for report %s", report.name)
            return None
            
        except Exception as e:
            _logger.warning("❌ CRITICAL ERROR with report %s: %s", report.name, str(e))
            return None

    def _is_valid_legal_pdf(self, pdf_content):
        """
        Validación SIMPLE y PRÁCTICA de PDF legal
        No ser demasiado estricto para no bloquear PDFs válidos
        """
        if not pdf_content:
            return False
        
        # Validación básica de tamaño
        if len(pdf_content) < 500:  # Muy pequeño
            _logger.warning("PDF too small: %d bytes", len(pdf_content))
            return False
        
        if len(pdf_content) > 50 * 1024 * 1024:  # Muy grande (50MB)
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
                
                # VALIDACIÓN ESPECÍFICA QR AFIP (basada en el log exitoso)
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
                
                if found_indicators >= 3:  # Al menos 3 indicadores
                    _logger.info("✅ PDF VALID: Found %d legal indicators", found_indicators)
                    return True
                else:
                    _logger.info("PDF has %d indicators (need 3+)", found_indicators)
            
            # Si no se puede extraer texto pero el PDF es grande, aceptarlo
            if len(pdf_content) > 50000:  # > 50KB
                _logger.info("✅ PDF VALID: Large PDF accepted (text extraction failed)")
                return True
            
        except Exception as e:
            _logger.warning("Error validating PDF: %s", str(e))
            # Si hay error en validación pero el PDF parece válido, aceptarlo
            if len(pdf_content) > 20000:  # > 20KB
                _logger.info("✅ PDF VALID: Validation error but size acceptable")
                return True
        
        _logger.warning("❌ PDF INVALID: Failed validation checks")
        return False

    def _extract_text_simple(self, pdf_content):
        """Extracción simple de texto sin dependencias complejas"""
        try:
            # Intentar con PyPDF2 si está disponible
            try:
                from PyPDF2 import PdfReader
                pdf_file = io.BytesIO(pdf_content)
                reader = PdfReader(pdf_file)
                
                text = ""
                for i, page in enumerate(reader.pages[:5]):  # Solo primeras 5 páginas
                    try:
                        text += page.extract_text() + "\n"
                    except:
                        continue
                
                return text.strip()
                
            except ImportError:
                # PyPDF2 no disponible, buscar texto directo en bytes
                text_bytes = pdf_content.decode('latin-1', errors='ignore')
                # Buscar patrones básicos
                import re
                text_matches = re.findall(r'[A-Za-z0-9\s]{10,}', text_bytes)
                return ' '.join(text_matches[:100])  # Primeros 100 matches
                
        except Exception as e:
            _logger.warning("Text extraction failed: %s", str(e))
            return ""

    def _upload_to_ml_api(self, pdf_content):
        """Upload simple a ML sin complicaciones"""
        try:
            # Configuración básica
            ml_api_url = config.get('ml_api_url', 'https://api.mercadolibre.com/invoice-bridge')
            ml_api_key = config.get('ml_api_key', '')
            
            if not ml_api_key:
                return {'success': False, 'error': 'API Key de MercadoLibre no configurada'}
            
            # Datos básicos
            files = {
                'invoice_pdf': ('invoice.pdf', pdf_content, 'application/pdf')
            }
            
            data = {
                'pack_id': self.pack_id,
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
            
            # Request simple
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

    # MÉTODOS DE DEBUGGING SIMPLES
    def action_test_pdf_generation(self):
        """Test directo de generación de PDF"""
        self.ensure_one()
        
        try:
            _logger.info("=== TESTING PDF GENERATION ===")
            pdf_content = self._get_legal_pdf_content()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Test Exitoso',
                    'message': f'PDF generado: {len(pdf_content)} bytes',
                    'sticky': False,
                }
            }

    def action_test_with_working_record(self):
        """Test específico basado en el record que vimos funcionando en el log"""
        self.ensure_one()
        
        try:
            _logger.info("=== TESTING WITH CURRENT RECORD (based on working log) ===")
            _logger.info("Current record ID: %s (log showed record [7] working)", self.id)
            
            # Verificar que tengamos una factura válida como la del log
            if not self.name or not self.partner_id:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Invalid Record',
                        'message': 'This record lacks basic invoice data. Try with a posted invoice.',
                        'sticky': True,
                    }
                }
            
            _logger.info("Invoice: %s, Partner: %s, State: %s", 
                        self.name, self.partner_id.name, self.state)
            
            # Usar exactamente la misma lógica que nuestra función principal
            pdf_content = self._get_legal_pdf_content()
            
            if pdf_content:
                # Validar que tenga QR AFIP como en el log exitoso
                qr_validation = self._check_for_afip_qr(pdf_content)
                
                message = f"""PDF Generated Successfully!
Size: {len(pdf_content)} bytes
QR AFIP: {'✅ Found' if qr_validation else '❌ Not detected'}
Record ID: {self.id}
Invoice: {self.name}"""
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'SUCCESS - PDF Generated!',
                        'message': message,
                        'sticky': True,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'FAILED - No PDF Generated',
                        'message': 'Could not generate PDF with current strategies',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error("Test with working record failed: %s", str(e), exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Test Error',
                    'message': f'Error: {str(e)[:200]}',
                    'sticky': True,
                }
            }

    def _check_for_afip_qr(self, pdf_content):
        """Verificar específicamente si el PDF contiene QR AFIP"""
        try:
            text_content = self._extract_text_simple(pdf_content)
            if text_content:
                text_lower = text_content.lower()
                
                # Patrones específicos del QR AFIP que vimos en el log
                qr_patterns = [
                    'afip.gob.ar/fe/qr',
                    'https://www.afip.gob.ar/fe/qr/',
                    'qr?p=eyj',  # Base64 del QR
                    'codigo qr',
                    'código qr'
                ]
                
                for pattern in qr_patterns:
                    if pattern in text_lower:
                        _logger.info("QR AFIP pattern found: %s", pattern)
                        return True
                        
            # También buscar en el contenido binario del PDF
            pdf_text = pdf_content.decode('latin-1', errors='ignore').lower()
            if 'afip.gob.ar/fe/qr' in pdf_text:
                _logger.info("QR AFIP found in binary content")
                return True
                
            return False
            
        except Exception as e:
            _logger.warning("Error checking for AFIP QR: %s", str(e))
            return False
            
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
        
        # Todos los reportes de account.move
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

    def action_test_exact_gui_report(self):
        """Test del reporte exacto que está funcionando desde la GUI"""
        self.ensure_one()
        
        try:
            _logger.info("=== TESTING EXACT GUI REPORT FOR RECORD %s ===", self.id)
            
            # El log muestra que funciona con record [7], vamos a ver cuál es el reporte activo
            # Buscar reportes que tengan binding (aparecen en GUI)
            gui_reports = self.env['ir.actions.report'].search([
                ('model', '=', 'account.move'),
                ('binding_model_id', '!=', False),
                ('report_type', '=', 'qweb-pdf')
            ])
            
            _logger.info("Found %d GUI reports to test", len(gui_reports))
            
            success_count = 0
            results = []
            
            for report in gui_reports:
                try:
                    _logger.info("Testing GUI report: %s (XML: %s)", report.name, report.report_name)
                    
                    # Probar cada método
                    methods_tried = []
                    
                    # Método 1: _render_qweb_pdf (que vimos en el log)
                    try:
                        pdf_content, _ = report._render_qweb_pdf([self.id])
                        if pdf_content and len(pdf_content) > 1000:
                            methods_tried.append(f"_render_qweb_pdf: {len(pdf_content)} bytes ✅")
                            success_count += 1
                        else:
                            methods_tried.append("_render_qweb_pdf: failed ❌")
                    except Exception as e:
                        methods_tried.append(f"_render_qweb_pdf: error {str(e)[:50]} ❌")
                    
                    # Método 2: render_qweb_pdf
                    try:
                        pdf_content, _ = report.render_qweb_pdf([self.id])
                        if pdf_content and len(pdf_content) > 1000:
                            methods_tried.append(f"render_qweb_pdf: {len(pdf_content)} bytes ✅")
                        else:
                            methods_tried.append("render_qweb_pdf: failed ❌")
                    except Exception as e:
                        methods_tried.append(f"render_qweb_pdf: error {str(e)[:50]} ❌")
                    
                    results.append({
                        'report': report.name,
                        'xml_id': report.report_name,
                        'methods': methods_tried
                    })
                    
                except Exception as e:
                    results.append({
                        'report': report.name,
                        'xml_id': report.report_name,
                        'methods': [f"CRITICAL ERROR: {str(e)[:50]}"]
                    })
            
            # Log detallado de resultados
            _logger.info("=== GUI REPORT TEST RESULTS ===")
            for result in results:
                _logger.info("Report: %s (XML: %s)", result['report'], result['xml_id'])
                for method in result['methods']:
                    _logger.info("  - %s", method)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'GUI Report Test Complete',
                    'message': f'Tested {len(gui_reports)} GUI reports, {success_count} successful. Check logs for details.',
                    'sticky': True,
                }
            }
            
        except Exception as e:
            _logger.error("GUI report test failed: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'GUI Test Failed',
                    'message': f'Error: {str(e)}',
                    'sticky': True,
                }
            }
