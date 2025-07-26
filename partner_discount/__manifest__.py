# -*- coding: utf-8 -*-
{
    'name': 'Partner Discount Configuration',
    'version': '17.0.1.0.5',
    'category': 'Sales/Purchase',
    'summary': 'Configure automatic discounts per partner for sales and purchases',
    'description': """
Partner Discount Configuration
===============================

This module allows you to configure automatic discounts per partner that will be 
applied automatically to order lines:

Features:
* Customer discount: Applied automatically to sales order lines
* Supplier discount: Applied automatically to purchase order lines
* Percentage-based discounts with intuitive interface
* Automatic application when adding products to order lines

Usage:
1. Go to a Partner form
2. Set the desired discount percentage in the Sales tab
3. Create sales/purchase orders - discounts will be applied automatically

Note: Discounts are only applied to new lines when the discount field is empty (0).
    """,
    'author': 'Sinergia Pyme sas',
    'website': 'https://www.sinergiapyme.com',
    'depends': ['sale', 'purchase'],
    'data': [
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
