# -*- coding: utf-8 -*-

from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    customer_discount = fields.Float(
        string='Customer Discount (%)',
        help="Automatic discount percentage applied to sales order lines for this customer",
        digits=(5, 2),
        default=0.0
    )
    
    supplier_discount = fields.Float(
        string='Supplier Discount (%)',
        help="Automatic discount percentage applied to purchase order lines from this supplier",
        digits=(5, 2),
        default=0.0
    )
