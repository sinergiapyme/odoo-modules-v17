# -*- coding: utf-8 -*-
import logging
import os
import base64
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    """
    Migrar archivos existentes para crear attachments de respaldo
    Solo se ejecuta al ACTUALIZAR el módulo, no en instalación nueva
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    
    _logger.info("Migrando archivos existentes a nuevo sistema con respaldo...")
    
    # Buscar archivos sin attachment
    files_to_migrate = env['website.public.file'].search([
        ('attachment_id', '=', False)
    ])
    
    if not files_to_migrate:
        _logger.info("No hay archivos para migrar")
        return
    
    _logger.info(f"Encontrados {len(files_to_migrate)} archivos para agregar respaldo")
    
    migrated = 0
    errors = 0
    
    for file_record in files_to_migrate:
        try:
            # Si tiene datos binarios, crear attachment
            if file_record.file_data:
                attachment = env['ir.attachment'].create({
                    'name': file_record.file_name,
                    'datas': file_record.file_data,
                    'res_model': 'website.public.file',
                    'res_id': file_record.id,
                    'public': True,
                    'mimetype': file_record.mimetype or 'application/octet-stream',
                })
                
                file_record.attachment_id = attachment
                migrated += 1
                _logger.info(f"✓ Respaldo creado para: {file_record.name}")
            else:
                # Intentar leer desde filesystem
                filestore_path = env['ir.attachment']._filestore()
                safe_filename = f"public_{file_record.id}_{file_record.file_name}"
                file_path = os.path.join(filestore_path, 'public_files', safe_filename)
                
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
                    
                    file_data_base64 = base64.b64encode(file_content).decode('utf-8')
                    
                    # Actualizar file_data si no existe
                    file_record.file_data = file_data_base64
                    
                    # Crear attachment
                    attachment = env['ir.attachment'].create({
                        'name': file_record.file_name,
                        'datas': file_data_base64,
                        'res_model': 'website.public.file',
                        'res_id': file_record.id,
                        'public': True,
                        'mimetype': file_record.mimetype or 'application/octet-stream',
                    })
                    
                    file_record.attachment_id = attachment
                    migrated += 1
                    _logger.info(f"✓ Respaldo creado desde disco para: {file_record.name}")
                else:
                    _logger.warning(f"✗ No se encontró archivo para: {file_record.name}")
                    errors += 1
                    
        except Exception as e:
            _logger.error(f"✗ Error migrando {file_record.name}: {str(e)}")
            errors += 1
    
    _logger.info(f"""
    ========================================
    Migración completada:
    - Archivos procesados: {len(files_to_migrate)}
    - Respaldos creados: {migrated}
    - Errores: {errors}
    ========================================
    """)
