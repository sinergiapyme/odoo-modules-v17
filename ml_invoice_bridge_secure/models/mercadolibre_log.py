# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class MercadoLibreLog(models.Model):
    _name = 'mercadolibre.log'
    _description = 'MercadoLibre Operation Log'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char(string='Name', compute='_compute_display_name', store=True)
    # 🔧 CORRECCIÓN CRÍTICA: required=False para permitir logs de cron
    invoice_id = fields.Many2one('account.move', string='Invoice', required=False, ondelete='cascade')
    ml_pack_id = fields.Char(string='Pack ID')
    status = fields.Selection([('success', 'Success'), ('error', 'Error')], string='Status', required=True)
    message = fields.Text(string='Message')
    ml_response = fields.Text(string='ML Response')

    @api.depends('invoice_id', 'status')
    def _compute_display_name(self):
        for log in self:
            if log.invoice_id:
                log.display_name = "%s - %s" % (log.invoice_id.name, log.status.title())
            else:
                # 🔧 MEJORADO: Mejor identificación de logs de cron
                log.display_name = "CRON - %s" % log.status.title()

    @api.model
    def create_log(self, invoice_id, status, message, **kwargs):
        """Método estándar para crear logs de facturas"""
        return self.create({
            'invoice_id': invoice_id,
            'status': status,
            'message': message,
            'ml_pack_id': kwargs.get('ml_pack_id'),
            'ml_response': kwargs.get('ml_response'),
        })

    @api.model
    def create_cron_log(self, status, message, **kwargs):
        """🆕 NUEVO: Método específico para logs de cron sin factura"""
        return self.create({
            'invoice_id': False,  # Permitido para logs de cron
            'status': status,
            'message': message,
            'ml_pack_id': kwargs.get('ml_pack_id'),
            'ml_response': kwargs.get('ml_response'),
        })

    def action_view_invoice(self):
        """Abrir la factura relacionada al log"""
        self.ensure_one()
        
        if not self.invoice_id:
            raise UserError(_('No hay factura asociada a este log'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice: %s') % self.invoice_id.name,
            'view_mode': 'form',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'target': 'current',
            'context': {
                'default_move_type': self.invoice_id.move_type,
            }
        }

    def action_retry_upload(self):
        """Reintentar upload de la factura desde el log"""
        self.ensure_one()
        
        # Validaciones básicas
        if not self.invoice_id:
            raise UserError(_('No hay factura asociada a este log'))
        
        if self.status == 'success':
            raise UserError(_('Esta factura ya fue subida exitosamente'))
        
        if self.invoice_id.state != 'posted':
            raise UserError(_('Solo se pueden subir facturas validadas'))
        
        if not self.invoice_id.is_ml_sale:
            raise UserError(_('Esta factura no es de MercadoLibre'))
        
        if self.invoice_id.ml_uploaded:
            raise UserError(_('Esta factura ya está marcada como subida'))
        
        try:
            result = self.invoice_id.action_upload_to_ml()
            
            self.write({
                'status': 'success',
                'message': _('Retry successful: %s') % (result.get('params', {}).get('message', 'Upload completed'))
            })
            
            return result
            
        except UserError as e:
            self.write({
                'message': _('Retry failed: %s') % str(e)
            })
            raise
            
        except Exception as e:
            error_msg = _('Retry failed with unexpected error: %s') % str(e)
            self.write({
                'message': error_msg
            })
            raise UserError(error_msg)

    def action_retry_upload_bulk(self):
        """Reintentar upload de múltiples logs seleccionados"""
        failed_logs = self.filtered(lambda l: l.status == 'error')
        
        if not failed_logs:
            raise UserError(_('No hay logs con errores seleccionados'))
        
        success_count = 0
        error_count = 0
        
        for log in failed_logs:
            try:
                log.action_retry_upload()
                success_count += 1
            except Exception:
                error_count += 1
                continue
        
        message = _('Retry completed: %d successful, %d failed') % (success_count, error_count)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Retry Results'),
                'message': message,
                'type': 'success' if success_count > 0 else 'warning'
            }
        }
