# -*- coding: utf-8 -*-

from . import models

def post_init_hook(cr, registry):
    """Hook ejecutado después de instalar el módulo"""
    import logging
    _logger = logging.getLogger(__name__)
    
    _logger.info("=== MercadoLibre Invoice Bridge - Post Install ===")
    _logger.info("✅ Módulo instalado correctamente")
    _logger.info("📋 Próximos pasos:")
    _logger.info("   1. Configurar tokens ML en MercadoLibre > Configuration")
    _logger.info("   2. Hacer test de conexión")
    _logger.info("   3. Verificar facturas ML existentes")
    _logger.info("   4. Activar auto-upload si es necesario")

def uninstall_hook(cr, registry):
    """Hook ejecutado antes de desinstalar el módulo"""
    import logging
    _logger = logging.getLogger(__name__)
    
    _logger.info("=== MercadoLibre Invoice Bridge - Uninstall ===")
    _logger.warning("⚠️  Datos de configuración y logs se mantendrán")
    _logger.info("✅ Módulo desinstalado correctamente")
