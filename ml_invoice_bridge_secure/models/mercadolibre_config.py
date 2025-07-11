# -*- coding: utf-8 -*-

import logging
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class MercadoLibreConfig(models.Model):
    _name = 'mercadolibre.config'
    _description = 'MercadoLibre Configuration'
    _rec_name = 'name'

    name = fields.Char(string='Configuration Name', required=True)
    
    # OAuth Configuration COMPLETA
    client_id = fields.Char(string='Client ID', required=True, help='Client ID de la aplicación MercadoLibre')
    client_secret = fields.Char(string='Client Secret', required=True, help='Client Secret de la aplicación MercadoLibre')
    access_token = fields.Char(string='Access Token', required=True, help='Token de acceso actual')
    refresh_token = fields.Char(string='Refresh Token', help='Token para renovar automáticamente')
    ml_user_id = fields.Char(string='MercadoLibre User ID', help='ID del usuario ML asociado')
    
    # Status
    active = fields.Boolean(string='Active', default=True)
    auto_upload = fields.Boolean(
        string='Auto Upload', 
        default=False,
        help='ATENCIÓN: Solo activar cuando el módulo esté completamente estable. '
             'También requiere activar el cron desde Configuración > Tareas Programadas'
    )
    api_status = fields.Selection([
        ('not_tested', 'Not Tested'),
        ('success', 'Connection OK'), 
        ('failed', 'Connection Failed'),
    ], default='not_tested', readonly=True)
    last_test = fields.Datetime(string='Last Test', readonly=True)
    last_token_refresh = fields.Datetime(string='Last Token Refresh', readonly=True)
    
    # Info del cron
    cron_status = fields.Char(string='Cron Status', compute='_compute_cron_status', store=False)

    @api.depends('auto_upload')
    def _compute_cron_status(self):
        for config in self:
            cron = self.env.ref('ml_invoice_bridge_secure.cron_auto_upload_ml_invoices', raise_if_not_found=False)
            if cron:
                if config.auto_upload and cron.active:
                    config.cron_status = '✅ Auto Upload ACTIVO'
                elif config.auto_upload and not cron.active:
                    config.cron_status = '⚠️ Config activa pero Cron DESACTIVADO'
                elif not config.auto_upload and cron.active:
                    config.cron_status = '⚠️ Cron activo pero Config DESACTIVADA'
                else:
                    config.cron_status = '❌ Auto Upload DESACTIVADO (seguro)'
            else:
                config.cron_status = '❓ Cron no encontrado'

    @api.constrains('active')
    def _check_single_active(self):
        if self.active and self.search_count([('active', '=', True), ('id', '!=', self.id)]) > 0:
            raise ValidationError(_('Solo puede haber una configuración activa'))

    @api.model
    def get_active_config(self):
        return self.search([('active', '=', True)], limit=1)

    def test_api_connection(self):
        """Test mejorado con manejo de tokens expirados"""
        self.ensure_one()
        try:
            headers = {'Authorization': f'Bearer {self.access_token}'}
            response = requests.get('https://api.mercadolibre.com/users/me', headers=headers, timeout=10)
            
            if response.status_code == 200:
                user_data = response.json()
                self.write({
                    'api_status': 'success',
                    'last_test': fields.Datetime.now(),
                    'ml_user_id': str(user_data.get('id', ''))
                })
                return {
                    'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {
                        'title': _('Success'), 
                        'message': _('Connected successfully\nUser: %s') % user_data.get('nickname', 'Unknown'),
                        'type': 'success'
                    }
                }
            elif response.status_code == 401:
                # Token expirado
                self.api_status = 'failed'
                if self.refresh_token:
                    return self.refresh_access_token()
                else:
                    raise UserError(_('Access token expirado. Renovar manualmente.'))
            else:
                self.api_status = 'failed'
                raise UserError(_('API connection failed: %s') % response.status_code)
        except Exception as e:
            self.api_status = 'failed'
            raise UserError(_('Connection error: %s') % str(e))

    def refresh_access_token(self):
        """Renovar access token usando refresh token"""
        self.ensure_one()
        if not self.refresh_token:
            raise UserError(_('Refresh Token requerido para renovar'))
        
        try:
            url = 'https://api.mercadolibre.com/oauth/token'
            data = {
                'grant_type': 'refresh_token',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token,
            }
            
            response = requests.post(url, data=data, timeout=10)
            
            if response.status_code == 200:
                token_data = response.json()
                self.write({
                    'access_token': token_data.get('access_token'),
                    'refresh_token': token_data.get('refresh_token'),
                    'last_token_refresh': fields.Datetime.now(),
                    'api_status': 'not_tested'
                })
                
                return {
                    'type': 'ir.actions.client', 'tag': 'display_notification',
                    'params': {'title': _('Token Renewed'), 'message': _('Access token renovado exitosamente'), 'type': 'success'}
                }
            else:
                raise UserError(_('Token refresh failed: %s') % response.status_code)
        except Exception as e:
            raise UserError(_('Token refresh error: %s') % str(e))

    def action_open_cron_settings(self):
        """Abrir configuración del cron directamente"""
        cron = self.env.ref('ml_invoice_bridge_secure.cron_auto_upload_ml_invoices', raise_if_not_found=False)
        if cron:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Auto Upload Cron Settings'),
                'view_mode': 'form',
                'res_model': 'ir.cron',
                'res_id': cron.id,
                'target': 'new',
            }
        else:
            raise UserError(_('Cron no encontrado'))
