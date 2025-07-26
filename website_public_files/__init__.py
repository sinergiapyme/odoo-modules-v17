from . import models
from . import controllers
import os
import logging

_logger = logging.getLogger(__name__)

def post_init_hook(env):
    """Crear directorio público al instalar el módulo"""
    try:
        filestore_path = env['ir.attachment']._filestore()
        upload_dir = os.path.join(filestore_path, 'public_files')
        os.makedirs(upload_dir, mode=0o755, exist_ok=True)
        _logger.info(f"Directorio público creado: {upload_dir}")
    except Exception as e:
        _logger.error(f"Error creando directorio público: {e}")
