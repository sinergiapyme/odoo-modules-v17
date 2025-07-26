from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
import os
import logging

_logger = logging.getLogger(__name__)

class WebsitePublicFile(models.Model):
    _name = 'website.public.file'
    _description = 'Website Public File Manager'
    _order = 'create_date desc'

    name = fields.Char(string='Name', required=True)
    file_data = fields.Binary(string='File', required=True)
    file_name = fields.Char(string='File Name', required=True)
    public_url = fields.Char(string='Public URL', readonly=True)
    file_size = fields.Integer(string='File Size', readonly=True)
    mimetype = fields.Char(string='MIME Type', readonly=True)
    is_image = fields.Boolean(string='Is Image', readonly=True)
    is_video = fields.Boolean(string='Is Video', readonly=True)
    is_pdf = fields.Boolean(string='Is PDF', readonly=True)
    active = fields.Boolean(string='Active', default=True)
    description = fields.Text(string='Description')
    
    # ÚNICO CAMPO NUEVO: para respaldo
    attachment_id = fields.Many2one('ir.attachment', string='Attachment', ondelete='cascade')
    
    @api.constrains('file_data')
    def _check_file_size(self):
        for record in self:
            if record.file_size > 100 * 1024 * 1024:  # 100MB limit
                raise UserError(_('File size cannot exceed 100MB'))

    @api.model
    def create(self, vals):
        record = super().create(vals)
        
        # Directorio seguro dentro del filestore de Odoo
        filestore_path = self.env['ir.attachment']._filestore()
        upload_dir = os.path.join(filestore_path, 'public_files')
        os.makedirs(upload_dir, exist_ok=True)
        
        file_content = base64.b64decode(vals['file_data'])
        safe_filename = f"public_{record.id}_{vals['file_name']}"
        file_path = os.path.join(upload_dir, safe_filename)
        
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        # URL pública del controlador
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        public_url = f"{base_url}/public_files/{record.id}/{vals['file_name']}"
        
        # Detectar tipo MIME usando mimetypes
        import mimetypes
        mimetype, _ = mimetypes.guess_type(vals['file_name'])
        if not mimetype:
            mimetype = 'application/octet-stream'
        
        image_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/svg+xml', 'image/webp', 'image/bmp', 'image/tiff']
        video_types = ['video/mp4', 'video/avi', 'video/mov', 'video/wmv', 'video/webm', 'video/mkv']
        
        super(WebsitePublicFile, record).write({
            'public_url': public_url,
            'file_size': len(file_content),
            'mimetype': mimetype,
            'is_image': mimetype in image_types,
            'is_video': mimetype in video_types,
            'is_pdf': mimetype == 'application/pdf',
        })
        
        # MEJORA: Crear attachment para respaldo
        try:
            attachment = self.env['ir.attachment'].create({
                'name': vals['file_name'],
                'datas': vals['file_data'],
                'res_model': 'website.public.file',
                'res_id': record.id,
                'public': True,
                'mimetype': mimetype,
            })
            record.attachment_id = attachment
            _logger.info(f"Respaldo creado para: {record.name}")
        except Exception as e:
            _logger.warning(f"No se pudo crear respaldo: {e}")
            # No falla si no puede crear respaldo
        
        return record

    def write(self, vals):
        result = super().write(vals)
        if 'file_data' in vals and vals['file_data']:
            for record in self:
                try:
                    filestore_path = self.env['ir.attachment']._filestore()
                    upload_dir = os.path.join(filestore_path, 'public_files')
                    
                    # LÍNEA CRÍTICA AGREGADA: Asegurar que el directorio existe
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    file_content = base64.b64decode(vals['file_data'])
                    safe_filename = f"public_{record.id}_{record.file_name}"
                    file_path = os.path.join(upload_dir, safe_filename)
                    
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    record.file_size = len(file_content)
                    
                    # MEJORA: Actualizar attachment si existe
                    if record.attachment_id:
                        record.attachment_id.write({
                            'datas': vals['file_data'],
                            'name': record.file_name,
                        })
                    
                except Exception as e:
                    _logger.error(f"Error escribiendo archivo {record.file_name}: {str(e)}")
                    raise UserError(_(f"Error al guardar el archivo: {str(e)}"))
        return result

    def unlink(self):
        for record in self:
            try:
                filestore_path = self.env['ir.attachment']._filestore()
                safe_filename = f"public_{record.id}_{record.file_name}"
                file_path = os.path.join(filestore_path, 'public_files', safe_filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                _logger.warning(f"Error eliminando archivo: {e}")
        return super().unlink()

    def action_copy_url(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('URL Copied'),
                'message': self.public_url,
                'type': 'success',
            }
        }
