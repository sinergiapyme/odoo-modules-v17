# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.tools import float_round, float_compare
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    price_margin_percent = fields.Float(
        string='Margen %',
        help='Porcentaje de margen sobre el costo. Puede ser positivo (ganancia) o negativo (pérdida). '
             'Si es 0, el precio de venta será igual al costo.',
        default=0.0,
        digits='Product Price',
    )
    
    automatic_price_update = fields.Boolean(
        string='Actualización Automática de Precio',
        default=True,
        help='Si está activado, el precio se actualizará cuando use el botón o el cron.'
    )
    
    def _calculate_price_from_margin(self):
        """Método auxiliar para calcular el precio basado en el margen"""
        self.ensure_one()
        # Obtener el costo actual
        cost = self.standard_price
        
        _logger.info('Calculando precio para %s - Costo: %s, Margen: %s%%', 
                    self.display_name, cost, self.price_margin_percent)
        
        # Calcular el precio con el margen
        if self.price_margin_percent == 0:
            new_price = cost
        else:
            # Precio = Costo * (1 + Margen/100)
            new_price = cost * (1 + self.price_margin_percent / 100.0)
        
        _logger.info('Nuevo precio calculado: %s', new_price)
        
        # Redondear según la precisión decimal configurada
        precision = self.env['decimal.precision'].precision_get('Product Price')
        return float_round(new_price, precision_digits=precision)
    
    def action_update_price_from_margin(self):
        """Acción MANUAL para actualizar el precio - SE LLAMA DESDE EL BOTÓN"""
        updated_count = 0
        errors = []
        
        for product in self:
            try:
                if not product.automatic_price_update:
                    continue
                    
                old_price = product.list_price
                new_price = product._calculate_price_from_margin()
                
                # Comparar precios
                precision = self.env['decimal.precision'].precision_get('Product Price')
                if float_compare(old_price, new_price, precision_digits=precision) != 0:
                    # ACTUALIZAR DIRECTAMENTE sin triggers
                    product.with_context(skip_margin_trigger=True).write({
                        'list_price': new_price
                    })
                    updated_count += 1
                    _logger.info('Precio actualizado: %s: %s -> %s', 
                               product.display_name, old_price, new_price)
                    
            except Exception as e:
                errors.append(f"{product.display_name}: {str(e)}")
                _logger.error('Error actualizando %s: %s', product.display_name, str(e))
        
        # Preparar mensaje
        if errors:
            message = f'Se actualizaron {updated_count} productos. Errores en: {", ".join(errors)}'
            msg_type = 'warning'
        elif updated_count:
            message = f'Precio actualizado correctamente: ${self.list_price:,.2f}'
            msg_type = 'success'
        else:
            message = 'El precio ya está actualizado.'
            msg_type = 'info'
        
        # OPCIÓN MÁS EFICIENTE: Solo mostrar notificación
        # El campo se actualizará automáticamente en la vista gracias a Odoo
        notification = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Actualización de Precio',
                'message': message,
                'type': msg_type,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
        
        # Si es un solo producto y se actualizó, forzar el refresco del campo
        if len(self) == 1 and updated_count > 0:
            # Esto actualiza solo los campos modificados sin recargar toda la vista
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'product.template',
                'res_id': self.id,
                'view_mode': 'form',
                'view_id': self.env.ref('product.product_template_form_view').id,
                'target': 'current',
                'flags': {
                    'mode': 'edit',
                    'form': {'reload': False}
                },
            }
        
        return notification
    
    @api.model
    def cron_update_prices_from_margin(self, batch_size=500):
        """Método para el CRON - actualización masiva programada"""
        start_time = datetime.now()
        
        # Solo productos activos con actualización automática
        domain = [
            ('automatic_price_update', '=', True),
            ('active', '=', True),
            ('price_margin_percent', '!=', 0),  # Solo si tienen margen definido
        ]
        
        total_products = self.search_count(domain)
        processed = 0
        updated = 0
        errors = 0
        
        _logger.info('CRON: Iniciando actualización de precios. Productos: %s', total_products)
        
        # Procesar en lotes
        offset = 0
        while offset < total_products:
            batch = self.search(domain, limit=batch_size, offset=offset)
            if not batch:
                break
                
            for product in batch:
                try:
                    old_price = product.list_price
                    new_price = product._calculate_price_from_margin()
                    
                    precision = self.env['decimal.precision'].precision_get('Product Price')
                    if float_compare(old_price, new_price, precision_digits=precision) != 0:
                        product.with_context(
                            skip_margin_trigger=True,
                            mail_notrack=True,
                        ).write({
                            'list_price': new_price
                        })
                        updated += 1
                        
                except Exception as e:
                    errors += 1
                    _logger.error('CRON Error con %s: %s', product.display_name, str(e))
            
            processed += len(batch)
            offset += batch_size
            self.env.cr.commit()
            
            if processed % 2500 == 0:
                _logger.info('CRON Progreso: %s/%s procesados, %s actualizados', 
                           processed, total_products, updated)
        
        _logger.info('CRON Completado: %s procesados, %s actualizados, %s errores en %s segundos',
                    processed, updated, errors, (datetime.now() - start_time).total_seconds())
        
        return True
    
    def write(self, vals):
        """Override simplificado - NO hace cálculos automáticos"""
        # Solo evitar recursión
        if self.env.context.get('skip_margin_trigger'):
            return super().write(vals)
            
        return super().write(vals)
    
    @api.onchange('price_margin_percent')
    def _onchange_margin_preview(self):
        """Muestra preview del precio cuando cambia el margen (sin guardar)"""
        if self.automatic_price_update and self.standard_price > 0:
            # Solo mostrar, no guardar
            new_price = self._calculate_price_from_margin()
            # Esto mostrará el nuevo precio en la vista pero no lo guardará hasta que el usuario guarde
            return {
                'warning': {
                    'title': 'Precio calculado',
                    'message': f'El nuevo precio será: ${new_price:,.2f}\nGuarde para aplicar el cambio.'
                }
            }
