# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # ====================================
    # EXTENDED FIELDS FOR HISTORY TRACKING
    # ====================================

    # History relationships
    interaction_ids = fields.One2many('interaction.history', 'product_id', string='Interactions')
    purchase_ids = fields.One2many('purchase.history', 'product_id', string='Purchase History')

    # Analytics
    interaction_count = fields.Integer(
        'Interaction Count', compute='_compute_product_analytics', store=True)
    purchase_count = fields.Integer(
        'Purchase Count', compute='_compute_product_analytics', store=True)
    total_sold_amount = fields.Float(
        'Total Sold Amount', compute='_compute_product_analytics', store=True)
    total_sold_quantity = fields.Integer(
        'Total Sold Quantity', compute='_compute_product_analytics', store=True)
    avg_selling_price = fields.Float(
        'Average Selling Price', compute='_compute_product_analytics', store=True)

    # Customer segmentation
    b2c_sales_count = fields.Integer('B2C Sales', compute='_compute_customer_segmentation', store=True)
    b2b_sales_count = fields.Integer('B2B Sales', compute='_compute_customer_segmentation', store=True)
    partner_sales_count = fields.Integer('Partner Sales', compute='_compute_customer_segmentation', store=True)

    # ====================================
    # COMPUTED METHODS
    # ====================================

    @api.depends('interaction_ids', 'purchase_ids.amount', 'purchase_ids.quantity')
    def _compute_product_analytics(self):
        """Compute product interaction and sales analytics"""
        for product in self:
            product.interaction_count = len(product.interaction_ids)
            product.purchase_count = len(product.purchase_ids)
            product.total_sold_amount = sum(product.purchase_ids.mapped('amount'))
            product.total_sold_quantity = sum(product.purchase_ids.mapped('quantity'))

            # Average selling price
            if product.purchase_count > 0:
                product.avg_selling_price = product.total_sold_amount / product.total_sold_quantity
            else:
                product.avg_selling_price = 0.0

    @api.depends('purchase_ids.partner_id.customer_type')
    def _compute_customer_segmentation(self):
        """Compute sales by customer type"""
        for product in self:
            b2c_sales = product.purchase_ids.filtered(lambda p: p.partner_id.customer_type == 'b2c')
            b2b_sales = product.purchase_ids.filtered(lambda p: p.partner_id.customer_type == 'b2b')
            partner_sales = product.purchase_ids.filtered(lambda p: p.partner_id.customer_type == 'partner')

            product.b2c_sales_count = len(b2c_sales)
            product.b2b_sales_count = len(b2b_sales)
            product.partner_sales_count = len(partner_sales)

    # ====================================
    # BUSINESS METHODS
    # ====================================

    def action_view_interactions(self):
        """View product interactions"""
        self.ensure_one()
        return {
            'name': _('Product Interactions'),
            'view_mode': 'tree,form',
            'res_model': 'interaction.history',
            'type': 'ir.actions.act_window',
            'domain': [('product_id', '=', self.id)],
            'context': {'default_product_id': self.id}
        }

    def action_view_purchase_history(self):
        """View product purchase history"""
        self.ensure_one()
        return {
            'name': _('Product Purchase History'),
            'view_mode': 'tree,form',
            'res_model': 'purchase.history',
            'type': 'ir.actions.act_window',
            'domain': [('product_id', '=', self.id)],
            'context': {'default_product_id': self.id}
        }

    def get_top_customers(self, limit=10):
        """Get top customers for this product"""
        self.ensure_one()
        purchase_data = self.env['purchase.history']._read_group(
            [('product_id', '=', self.id)],
            ['partner_id'],
            ['amount:sum', '__count'],
            orderby='amount:sum desc',
            limit=limit
        )
        return [(partner, amount_sum, count) for partner, amount_sum, count in purchase_data]

    # ====================================
    # SEARCH METHODS
    # ====================================

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """Enhanced search for product selection in interactions/purchases"""
        args = args or []
        if name:
            # Search by name, reference, or barcode
            domain = [
                '|', '|',
                ('name', operator, name),
                ('default_code', operator, name),
                ('barcode', operator, name)
            ]
            products = self.search(domain + args, limit=limit)
            return products.name_get()
        return super().name_search(name, args, operator, limit)
