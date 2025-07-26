# -*- coding: utf-8 -*-

from odoo import api, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.onchange('product_id')
    def _onchange_product_apply_discount(self):
        """
        Apply automatic customer discount when a product is selected.
        Only applies if no discount is currently set on the line.
        """
        if self.product_id and self.order_id.partner_id:
            partner_discount = self.order_id.partner_id.customer_discount
            if partner_discount > 0 and self.discount == 0:
                # Convert from percentage widget format (0.10) to discount field format (10.0)
                self.discount = partner_discount * 100
