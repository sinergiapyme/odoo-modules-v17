# -*- coding: utf-8 -*-
{
    'name': 'MercadoLibre Invoice Bridge - Production',
    'version': '17.0.3.0.0',
    'category': 'Sales/Accounting',
    'summary': 'Módulo para subir facturas legales de Odoo a MercadoLibre con soporte completo para facturación en lote',
    'description': '''
        MercadoLibre Invoice Bridge - Production Ready
        =============================================
        
        Módulo completo para sincronización de facturas entre Odoo y MercadoLibre:
        
        * ✅ Soporte completo para facturación individual y en lote
        * ✅ Transferencia automática de datos ML desde Sale Orders
        * ✅ Configuración automática de períodos AFIP para servicios
        * ✅ Generación de PDFs fiscales argentinos válidos
        * ✅ API robusta con manejo de errores y rate limiting
        * ✅ Sistema de logs completo para auditoría
        * ✅ Configuración OAuth segura con refresh tokens
        * ✅ Auto-upload programado con circuit breaker
        * ✅ Herramientas de debugging y corrección manual
        
        Compatibilidad:
        * Odoo v17 Community Edition
        * Localización Argentina de ADHOC
        * ODUMBO (sincronización de ventas ML)
    ''',
    'author': 'Sinergia Pyme SAS',
    'website': 'https://github.com/sinergiapyme/odoo-modules-v17',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'sale',
        'l10n_ar',
        'l10n_ar_ux',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        
        # Data
        'data/cron_data.xml',
        
        # Views - NOMBRES CORREGIDOS SEGÚN TU GITHUB
        'views/mercadolibre_config_views.xml',
        'views/mercadolibre_invoice_log_views.xml',
        'views/account_move_views.xml',
        'views/sale_order_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': False,
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
}
