# -*- coding: utf-8 -*-

from odoo import api, fields, models, _

class MercadoLibreLog(models.Model):
    _name = 'mercadolibre.log'
    _description = 'MercadoLibre Operation Log'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char(string='Name', compute='_compute_display_name', store=True)
    invoice_id = fields.Many2one('account.move', string='Invoice', required=True, ondelete='cascade')
    pack_id = fields.Char(string='Pack ID')
    status = fields.Selection([('success', 'Success'), ('error', 'Error')], string='Status', required=True)
    message = fields.Text(string='Message')
    ml_response = fields.Text(string='ML Response')

    @api.depends('invoice_id', 'status')
    def _compute_display_name(self):
        for log in self:
            if log.invoice_id:
                log.display_name = f"{log.invoice_id.name} - {log.status.title()}"
            else:
                log.display_name = f"Log - {log.status.title()}"

    @api.model
    def create_log(self, invoice_id, status, message, **kwargs):
        return self.create({
            'invoice_id': invoice_id,
            'status': status,
            'message': message,
            'pack_id': kwargs.get('pack_id'),
            'ml_response': kwargs.get('ml_response'),
        })

