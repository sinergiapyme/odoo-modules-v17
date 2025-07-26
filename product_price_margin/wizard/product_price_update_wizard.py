# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools import float_compare


class ProductPriceUpdateWizard(models.TransientModel):
    _name = 'product.price.update.wizard'
    _description = 'Asistente para Actualización Masiva de Precios'
    
    update_mode = fields.Selection([
        ('all', 'Todos los productos con actualización automática'),
        ('selected', 'Solo productos seleccionados'),
        ('category', 'Por categoría'),
        ('margin_range', 'Por rango de margen'),
    ], string='Modo de Actualización', default='selected', required=True)
    
    category_ids = fields.Many2many(
        'product.category',
        string='Categorías',
        help='Seleccione las categorías de productos a actualizar'
    )
    
    margin_min = fields.Float(
        string='Margen Mínimo %',
        help='Actualizar productos con margen mayor o igual a este valor'
    )
    
    margin_max = fields.Float(
        string='Margen Máximo %',
        help='Actualizar productos con margen menor o igual a este valor'
    )
    
    product_count = fields.Integer(
        string='Productos a Actualizar',
        compute='_compute_product_count',
        store=False
    )
    
    dry_run = fields.Boolean(
        string='Simulación',
        default=False,
        help='Si está marcado, mostrará los cambios sin aplicarlos'
    )
    
    @api.depends('update_mode', 'category_ids', 'margin_min', 'margin_max')
    def _compute_product_count(self):
        for wizard in self:
            domain = wizard._get_products_domain()
            wizard.product_count = self.env['product.template'].search_count(domain)
    
    def _get_products_domain(self):
        """Construye el dominio según el modo seleccionado"""
        self.ensure_one()
        domain = [('automatic_price_update', '=', True)]
        
        if self.update_mode == 'selected':
            # Obtener IDs del contexto
            active_ids = self.env.context.get('active_ids', [])
            if not active_ids:
                raise UserError('No hay productos seleccionados.')
            domain.append(('id', 'in', active_ids))
            
        elif self.update_mode == 'category':
            if not self.category_ids:
                raise UserError('Debe seleccionar al menos una categoría.')
            domain.append(('categ_id', 'in', self.category_ids.ids))
            
        elif self.update_mode == 'margin_range':
            if self.margin_min is not False:
                domain.append(('price_margin_percent', '>=', self.margin_min))
            if self.margin_max is not False:
                domain.append(('price_margin_percent', '<=', self.margin_max))
        
        return domain
    
    def action_update_prices(self):
        """Ejecuta la actualización de precios con optimización para grandes volúmenes"""
        self.ensure_one()
        
        # Obtener productos según el dominio
        domain = self._get_products_domain()
        products = self.env['product.template'].search(domain)
        
        if not products:
            raise UserError('No se encontraron productos para actualizar con los criterios seleccionados.')
        
        # Configuración
        BATCH_SIZE = 200
        update_data = []
        total_old_value = 0.0
        total_new_value = 0.0
        processed = 0
        
        # Procesar por lotes
        for i in range(0, len(products), BATCH_SIZE):
            batch = products[i:i + BATCH_SIZE]
            
            for product in batch:
                old_price = product.list_price
                new_price = product._calculate_price_from_margin()
                
                precision = self.env['decimal.precision'].precision_get('Product Price')
                if float_compare(old_price, new_price, precision_digits=precision) != 0:
                    update_data.append({
                        'product': product,
                        'old_price': old_price,
                        'new_price': new_price,
                        'difference': new_price - old_price,
                        'difference_percent': ((new_price - old_price) / old_price * 100) if old_price else 0
                    })
                    
                    # Para productos con stock, calcular el impacto en valor
                    if hasattr(product, 'qty_available'):
                        qty = product.qty_available
                        total_old_value += old_price * qty
                        total_new_value += new_price * qty
            
            processed += len(batch)
        
        if not update_data:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Actualización de Precios',
                    'message': 'No se encontraron cambios de precio para aplicar.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Si no es simulación, aplicar los cambios
        if not self.dry_run:
            updated = 0
            for i, data in enumerate(update_data):
                data['product'].with_context(
                    skip_margin_trigger=True,
                    mail_notrack=True
                ).write({
                    'list_price': data['new_price']
                })
                updated += 1
                
                # Commit cada 200 actualizaciones
                if updated % 200 == 0:
                    self.env.cr.commit()
        
        # Preparar mensaje de resultado
        message_lines = [
            f"{'SIMULACIÓN: ' if self.dry_run else ''}Se {'simularía actualizar' if self.dry_run else 'actualizaron'} {len(update_data)} producto(s).",
            f"Productos revisados: {len(products)}",
            f"Productos con cambios: {len(update_data)}",
        ]
        
        if total_old_value or total_new_value:
            impact = total_new_value - total_old_value
            message_lines.extend([
                f"Valor total anterior: ${total_old_value:,.2f}",
                f"Valor total nuevo: ${total_new_value:,.2f}",
                f"Impacto en inventario: ${impact:,.2f} ({impact/total_old_value*100:.1f}%)"
            ])
        
        # Crear un reporte detallado si hay muchos cambios
        if len(update_data) > 5:
            message_lines.append(f"\nPrimeros 5 cambios:")
            for data in update_data[:5]:
                product = data['product']
                message_lines.append(
                    f"- {product.display_name}: ${data['old_price']:.2f} → ${data['new_price']:.2f} "
                    f"({data['difference_percent']:+.1f}%)"
                )
            message_lines.append(f"... y {len(update_data) - 5} más.")
        else:
            # Mostrar todos los cambios si son pocos
            for data in update_data:
                product = data['product']
                message_lines.append(
                    f"- {product.display_name}: ${data['old_price']:.2f} → ${data['new_price']:.2f} "
                    f"({data['difference_percent']:+.1f}%)"
                )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Actualización de Precios Completada' if not self.dry_run else 'Simulación de Actualización',
                'message': '\n'.join(message_lines),
                'type': 'success' if not self.dry_run else 'info',
                'sticky': True,
            }
        }
