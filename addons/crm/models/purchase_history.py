# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PurchaseHistory(models.Model):
    _name = 'purchase.history'
    _description = 'Customer Purchase History'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'product_id'
    _order = 'purchase_date desc, id desc'

    # ====================================
    # CORE FIELDS
    # ====================================

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, ondelete='cascade', tracking=True)

    product_id = fields.Many2one(
        'product.product', string='Product', required=True, tracking=True)

    purchase_date = fields.Date(
        'Purchase Date', required=True, default=fields.Date.context_today, tracking=True)

    amount = fields.Float(
        'Amount', required=True, digits='Product Price', tracking=True)

    quantity = fields.Integer(
        'Quantity', required=True, default=1, tracking=True)

    # Computed fields
    unit_price = fields.Float(
        'Unit Price', compute='_compute_unit_price', store=True, readonly=True, digits='Product Price')

    # Additional fields
    currency_id = fields.Many2one(
        'res.currency', string='Currency', default=lambda self: self.env.company.currency_id)

    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('credit_card', 'Credit Card'),
        ('cheque', 'Cheque'),
        ('credit', 'On Credit'),
        ('other', 'Other')
    ], string='Payment Method', default='cash', tracking=True)

    order_reference = fields.Char('Order Reference')
    notes = fields.Text('Notes')
    user_id = fields.Many2one('res.users', string='Sales Rep', default=lambda self: self.env.user, tracking=True)

    # Related fields
    partner_customer_type = fields.Selection(
        related='partner_id.customer_type', string='Customer Type', readonly=True)
    product_category_id = fields.Many2one(
        related='product_id.categ_id', string='Product Category', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # ====================================
    # COMPUTED METHODS
    # ====================================

    @api.depends('amount', 'quantity')
    def _compute_unit_price(self):
        for purchase in self:
            if purchase.quantity > 0:
                purchase.unit_price = purchase.amount / purchase.quantity
            else:
                purchase.unit_price = 0.0

    # ====================================
    # BUSINESS METHODS - BUTTON ACTIONS
    # ====================================

    def create_repeat_purchase(self):
        """Create a repeat purchase order based on current one"""
        self.ensure_one()
        repeat_purchase = self.copy({
            'purchase_date': fields.Date.context_today(self),
            'order_reference': f"REPEAT-{self.order_reference}" if self.order_reference else False,
            'notes': f"Repeat purchase from {self.purchase_date}"
        })

        return {
            'name': _('Repeat Purchase'),
            'view_mode': 'form',
            'res_model': 'purchase.history',
            'res_id': repeat_purchase.id,
            'type': 'ir.actions.act_window',
            'target': 'current'
        }

    # ====================================
    # CRUD OVERRIDES
    # ====================================

    @api.model_create_multi
    def create(self, vals_list):
        purchases = super().create(vals_list)

        for purchase in purchases:
            if purchase.partner_id:
                purchase.partner_id._compute_analytics_fields()

                # Update type-specific analytics
                if purchase.partner_id.customer_type == 'b2c' and purchase.partner_id.b2c_info:
                    purchase.partner_id.b2c_info._compute_loyalty_points()
                elif purchase.partner_id.customer_type == 'b2b' and purchase.partner_id.b2b_info:
                    purchase.partner_id.b2b_info._compute_contract_value()
                elif purchase.partner_id.customer_type == 'partner' and purchase.partner_id.partner_info:
                    purchase.partner_id.partner_info._compute_partnership_metrics()

        return purchases

    def write(self, vals):
        result = super().write(vals)

        if any(field in vals for field in ['amount', 'quantity', 'purchase_date']):
            partners_to_update = self.mapped('partner_id')
            for partner in partners_to_update:
                partner._compute_analytics_fields()

                if partner.customer_type == 'b2c' and partner.b2c_info:
                    partner.b2c_info._compute_loyalty_points()
                elif partner.customer_type == 'b2b' and partner.b2b_info:
                    partner.b2b_info._compute_contract_value()
                elif partner.customer_type == 'partner' and partner.partner_info:
                    partner.partner_info._compute_partnership_metrics()

        return result

    def unlink(self):
        partners_to_update = self.mapped('partner_id')
        result = super().unlink()

        for partner in partners_to_update:
            partner._compute_analytics_fields()
            if partner.customer_type == 'b2c' and partner.b2c_info:
                partner.b2c_info._compute_loyalty_points()
            elif partner.customer_type == 'b2b' and partner.b2b_info:
                partner.b2b_info._compute_contract_value()
            elif partner.customer_type == 'partner' and partner.partner_info:
                partner.partner_info._compute_partnership_metrics()

        return result

    # ====================================
    # CONSTRAINTS
    # ====================================

    @api.constrains('amount', 'quantity')
    def _check_positive_values(self):
        for purchase in self:
            if purchase.amount <= 0:
                raise ValidationError(_("Purchase amount must be positive."))
            if purchase.quantity <= 0:
                raise ValidationError(_("Purchase quantity must be positive."))

    @api.constrains('purchase_date')
    def _check_purchase_date(self):
        for purchase in self:
            if purchase.purchase_date and purchase.purchase_date > fields.Date.context_today(self):
                raise ValidationError(_("Purchase date cannot be in the future."))

    _sql_constraints = [
        ('positive_amount', 'CHECK(amount > 0)', 'Purchase amount must be positive!'),
        ('positive_quantity', 'CHECK(quantity > 0)', 'Purchase quantity must be positive!'),
    ]
