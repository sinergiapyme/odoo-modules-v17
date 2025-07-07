# -*- coding: utf-8 -*-
{
    'name': 'MercadoLibre Invoice Bridge - Secure',
    'version': '17.0.2.1.0',  # Solo incremento menor
    'category': 'Sales',
    'summary': 'Módulo seguro para subir facturas de Odoo a MercadoLibre',
    'author': 'Tu Empresa',
    'depends': ['base', 'account', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/mercadolibre_config_views.xml',
        'views/mercadolibre_log_views.xml',
        'views/account_move_views.xml',
        'views/menu_views.xml',
        'data/cron_data.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
