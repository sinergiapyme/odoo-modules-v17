# -*- coding: utf-8 -*-

import logging
import re
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    """Extender Sale Order para manejar datos ML en facturación batch"""
    _inherit = 'sale.order'
    
    # Campos ML en Sale Order
    ml_pack_id = fields.Char(
        string='ML Pack ID', 
        help='MercadoLibre Pack ID from ODUMBO sync',
        tracking=True
    )
    is_ml_sale = fields.Boolean(
        string='Is ML Sale', 
        default=False, 
        help='Indica si es venta de MercadoLibre',
        tracking=True
    )
    
    @api.model
    def _get_ml_data_from_origin(self, origin_text):
        """Extrae datos ML del origin de forma segura"""
        if not origin_text:
            return {'is_ml_sale': False, 'ml_pack_id': False}
        
        try:
            # Buscar indicadores de MercadoLibre
            ml_indicators = ['mercadolibre', 'mercado libre', 'ml order', 'ml_']
            is_ml = any(indicator in origin_text.lower() for indicator in ml_indicators)
            
            if not is_ml:
                return {'is_ml_sale': False, 'ml_pack_id': False}
            
            # Extraer Pack ID usando regex mejorado
            pack_id_patterns = [
                r'MercadoLibre Order\s+(\d{10,20})',  # Patrón principal ODUMBO
                r'ML.*?(\d{13,20})',                   # Números largos después de ML
                r'Pack.*?(\d{10,20})',                 # Pack seguido de números
                r'Order.*?(\d{10,20})',                # Order seguido de números
            ]
            
            for pattern in pack_id_patterns:
                match = re.search(pattern, origin_text, re.IGNORECASE)
                if match:
                    pack_id = match.group(1)
                    if 10 <= len(pack_id) <= 20:  # Validar longitud típica Pack ID ML
                        _logger.info(f"Extracted ML Pack ID: {pack_id} from origin: {origin_text}")
                        return {'is_ml_sale': True, 'ml_pack_id': pack_id}
            
            # Si es ML pero no encontramos Pack ID
            _logger.warning(f"ML sale detected but no Pack ID found in: {origin_text}")
            return {'is_ml_sale': True, 'ml_pack_id': False}
            
        except Exception as e:
            _logger.error(f"Error ensuring ML data and AFIP periods transfer: {str(e)}")logger.error(f"Error extracting ML data from origin '{origin_text}': {str(e)}")
            return {'is_ml_sale': False, 'ml_pack_id': False}
    
    @api.model
    def create(self, vals):
        """Override create para auto-detectar datos ML en creación"""
        record = super().create(vals)
        
        # Auto-detectar ML si no está ya marcado
        if not record.is_ml_sale and record.origin:
            ml_data = self._get_ml_data_from_origin(record.origin)
            if ml_data['is_ml_sale']:
                record.write(ml_data)
                _logger.info(f"Auto-detected ML sale order: {record.name}, Pack ID: {ml_data.get('ml_pack_id', 'N/A')}")
        
        return record
    
    def _prepare_invoice(self):
        """Override para transferir datos ML Y configurar períodos AFIP"""
        invoice_vals = super()._prepare_invoice()
        
        # Transferir datos ML a la factura
        if self.is_ml_sale:
            invoice_vals.update({
                'is_ml_sale': True,
                'ml_pack_id': self.ml_pack_id,
            })
            _logger.info(f"Transferring ML data to invoice: Pack ID {self.ml_pack_id}")
        
        # Configurar períodos AFIP para servicios
        has_services = any(
            line.product_id and line.product_id.type == 'service' 
            for line in self.order_line
        )
        
        if has_services:
            # Usar fecha de la orden como período de servicio
            service_date = self.date_order.date() if self.date_order else fields.Date.today()
            
            invoice_vals.update({
                'afip_associated_period_from': service_date,
                'afip_associated_period_to': service_date,
            })
            _logger.info(f"Setting AFIP service period for SO {self.name}: {service_date}")
        
        return invoice_vals

class SaleAdvancePaymentInv(models.TransientModel):
    """Override del wizard de facturación para manejar batch correctamente"""
    _inherit = 'sale.advance.payment.inv'
    
    def _create_invoices(self, sale_orders):
        """Override para asegurar transferencia ML en facturación batch"""
        _logger.info(f"Creating invoices for {len(sale_orders)} sale orders in batch")
        
        # Llamar al método padre
        moves = super()._create_invoices(sale_orders)
        
        # Post-procesamiento: asegurar que datos ML se transfirieron
        self._ensure_ml_data_transfer(moves, sale_orders)
        
        return moves
    
    def _ensure_ml_data_transfer(self, invoices, sale_orders):
        """Asegurar que los datos ML Y períodos AFIP se transfirieron correctamente"""
        try:
            # Crear mapeo de sale_order -> invoice
            so_to_invoice = {}
            for invoice in invoices:
                for line in invoice.invoice_line_ids:
                    if line.sale_line_ids:
                        for sale_line in line.sale_line_ids:
                            so_to_invoice[sale_line.order_id.id] = invoice
                            break
            
            # Verificar y corregir datos ML + períodos AFIP
            fixed_count = 0
            for sale_order in sale_orders:
                if sale_order.id in so_to_invoice:
                    invoice = so_to_invoice[sale_order.id]
                    needs_fix = False
                    update_vals = {}
                    
                    # 1. Verificar datos ML
                    if sale_order.is_ml_sale:
                        if (not invoice.is_ml_sale or 
                            not invoice.ml_pack_id or 
                            invoice.ml_pack_id != sale_order.ml_pack_id):
                            update_vals.update({
                                'is_ml_sale': True,
                                'ml_pack_id': sale_order.ml_pack_id,
                            })
                            needs_fix = True
                    
                    # 2. Verificar períodos AFIP para servicios
                    has_services = any(
                        line.product_id and line.product_id.type == 'service' 
                        for line in invoice.invoice_line_ids
                    )
                    
                    if has_services:
                        # Verificar si faltan los períodos AFIP
                        if (not hasattr(invoice, 'afip_associated_period_from') or 
                            not invoice.afip_associated_period_from or
                            not hasattr(invoice, 'afip_associated_period_to') or
                            not invoice.afip_associated_period_to):
                            
                            service_date = sale_order.date_order.date() if sale_order.date_order else fields.Date.today()
                            update_vals.update({
                                'afip_associated_period_from': service_date,
                                'afip_associated_period_to': service_date,
                            })
                            needs_fix = True
                            _logger.info(f"Adding missing AFIP periods for invoice {invoice.name}: {service_date}")
                    
                    # Aplicar correcciones si es necesario
                    if needs_fix:
                        invoice.write(update_vals)
                        fixed_count += 1
                        _logger.info(f"Fixed data for invoice {invoice.name}: {update_vals}")
            
            if fixed_count > 0:
                _logger.info(f"Fixed ML data and AFIP periods for {fixed_count} invoices in batch process")
                
        except Exception as e:
            _
