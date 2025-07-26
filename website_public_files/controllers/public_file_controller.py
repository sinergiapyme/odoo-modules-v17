from odoo import http
from odoo.http import request
import os
import base64
import logging

_logger = logging.getLogger(__name__)

class PublicFileController(http.Controller):
    
    @http.route('/public_files/<int:file_id>/<filename>', type='http', auth='public', csrf=False)
    def download_public_file(self, file_id, filename, **kwargs):
        try:
            # Buscar el archivo en la base de datos
            file_record = request.env['website.public.file'].sudo().browse(file_id)
            
            if not file_record.exists() or not file_record.active:
                return request.not_found()
            
            # MEJORA: Intentar desde attachment primero (más confiable)
            if file_record.attachment_id and file_record.attachment_id.datas:
                file_content = base64.b64decode(file_record.attachment_id.datas)
            else:
                # Ruta del archivo en filestore (método original)
                filestore_path = request.env['ir.attachment']._filestore()
                safe_filename = f"public_{file_id}_{file_record.file_name}"
                file_path = os.path.join(filestore_path, 'public_files', safe_filename)
                
                if not os.path.exists(file_path):
                    _logger.error(f"Archivo no encontrado: {file_path}")
                    return request.not_found()
                
                # Leer y servir el archivo
                with open(file_path, 'rb') as f:
                    file_content = f.read()
            
            # Headers optimizados para CSP
            headers = [
                ('Content-Type', file_record.mimetype or 'application/octet-stream'),
                ('Content-Disposition', f'inline; filename="{filename}"'),
                ('Cache-Control', 'public, max-age=3600'),
                ('X-Content-Type-Options', 'nosniff'),
            ]
            
            # CSP específico para SVG con contenido embebido
            if file_record.mimetype == 'image/svg+xml':
                headers.append(('Content-Security-Policy', "default-src 'self' data: blob:; img-src 'self' data: blob:"))
            
            return request.make_response(file_content, headers=headers)
            
        except Exception as e:
            _logger.error(f"Error sirviendo archivo público: {e}")
            return request.not_found()
