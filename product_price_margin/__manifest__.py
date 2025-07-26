# -*- coding: utf-8 -*-
{
    'name': 'Product Price Margin',
    'version': '17.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Calcula el precio de venta basado en un margen sobre el costo',
    'description': """
        Este módulo permite calcular automáticamente el precio de venta (list_price)
        basándose en el costo (standard_price) más un porcentaje de margen.
        
        Características:
        - Campo de porcentaje de margen en cada producto
        - Actualización manual mediante acción contextual
        - Actualización automática mediante cron
        - Compatible con replenishment_cost
        - Optimizado para grandes volúmenes de productos
    """,
    'author': 'Sinergia Pyme',
    'website': 'https://www.sinergiapy.com',
    'depends': [
        'product',
        'sale_management',  # Para el menú de productos
        'stock',  # Para qty_available
        'product_replenishment_cost',  # Dependencia del módulo de costo de reposición
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/product_template_views.xml',
        'wizard/product_price_update_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
