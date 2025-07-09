# -*- coding: utf-8 -*-
{
    'name': 'MercadoLibre Invoice Bridge - Secure',
    'version': '17.0.2.2.0',  # Incremento por fix legal
    'category': 'Sales',
    'summary': 'Módulo seguro para subir facturas legales de Odoo a MercadoLibre',
    'author': 'Sinergia Pyme SAS',
    'depends': [
        'base', 
        'account', 
        'sale',
        'l10n_ar',  # CRÍTICO: Para reportes legales argentinos
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/mercadolibre_config_views.xml',
        'views/mercadolibre_invoice_log_views.xml',  # Corregido: elimina duplicado
        'views/account_move_views.xml',
        'views/menu_views.xml',
        'data/cron_data.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
