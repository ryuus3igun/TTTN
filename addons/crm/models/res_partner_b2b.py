# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartnerB2B(models.Model):
    _name = 'res.partner.b2b'
    _description = 'Partner B2B Extension - Business Customer Information'
    _rec_name = 'partner_id'

    # ====================================
    # CORE FIELDS
    # ====================================

    partner_id = fields.Many2one(
        'res.partner', string='Partner', required=True, ondelete='cascade',
        domain="[('customer_type', '=', 'b2b')]")

    # ====================================
    # SYSTEM FIELDS
    # ====================================

    create_at = fields.Datetime(
        'Created At', default=fields.Datetime.now, readonly=True,
        help="Timestamp when B2B information was created")

    # ====================================
    # B2B SPECIFIC FIELDS - MANUAL INPUT
    # ====================================

    vat = fields.Char(
        'VAT Number', size=32,
        help="Value Added Tax identification number")

    industry_id = fields.Many2one(
        'res.partner.industry', string='Industry',
        help="Industry sector of the business customer")

    # Additional B2B fields
    company_size = fields.Selection([
        ('micro', 'Micro (1-9 employees)'),
        ('small', 'Small (10-49 employees)'),
        ('medium', 'Medium (50-249 employees)'),
        ('large', 'Large (250+ employees)')
    ], string='Company Size', help="Number of employees classification")

    annual_revenue_range = fields.Selection([
        ('0-1m', '0-1M VND'),
        ('1m-10m', '1M-10M VND'),
        ('10m-100m', '10M-100M VND'),
        ('100m-1b', '100M-1B VND'),
        ('1b+', '1B+ VND')
    ], string='Annual Revenue Range')

    # ====================================
    # COMPUTED FIELDS - SYSTEM DERIVED
    # ====================================

    contract_value = fields.Float(
        'Active Contract Value', compute='_compute_contract_value', store=True,
        help="Total value of active contracts (from Sales module or purchase history)")

    department_interactions = fields.Integer(
        'Department Interactions', compute='_compute_department_interactions', store=True,
        help="Count of distinct departments involved in interactions")

    # B2B analytics
    avg_order_value = fields.Float(
        'Average Order Value', compute='_compute_b2b_analytics', store=True,
        help="Average purchase amount per transaction")

    purchase_frequency_days = fields.Float(
        'Purchase Frequency (Days)', compute='_compute_b2b_analytics', store=True,
        help="Average days between purchases")

    # ====================================
    # COMPUTED METHODS (same as before)
    # ====================================

    @api.depends('partner_id.purchase_ids.amount', 'partner_id.purchase_ids.purchase_date')
    def _compute_contract_value(self):
        """Calculate total active contract value from recent purchases"""
        for b2b in self:
            if b2b.partner_id and b2b.partner_id.purchase_ids:
                cutoff_date = fields.Date.today() - fields.Date.from_string('2024-01-01')
                cutoff_date = cutoff_date.replace(year=cutoff_date.year - 1)

                active_purchases = b2b.partner_id.purchase_ids.filtered(
                    lambda p: p.purchase_date >= cutoff_date
                )
                b2b.contract_value = sum(active_purchases.mapped('amount'))
            else:
                b2b.contract_value = 0.0

    @api.depends('partner_id.interaction_ids.description')
    def _compute_department_interactions(self):
        """Count distinct departments mentioned in interaction descriptions"""
        for b2b in self:
            if b2b.partner_id and b2b.partner_id.interaction_ids:
                departments = set()
                dept_keywords = {
                    'sales': ['sales', 'bán hàng', 'kinh doanh'],
                    'marketing': ['marketing', 'quảng cáo', 'truyền thông'],
                    'it': ['it', 'công nghệ', 'technical', 'kỹ thuật'],
                    'hr': ['hr', 'nhân sự', 'human resource'],
                    'finance': ['finance', 'tài chính', 'kế toán', 'accounting'],
                    'operations': ['operations', 'vận hành', 'sản xuất', 'production'],
                    'procurement': ['procurement', 'mua hàng', 'thu mua'],
                    'legal': ['legal', 'pháp lý', 'luật']
                }

                descriptions = b2b.partner_id.interaction_ids.mapped('description')
                for desc in descriptions:
                    if desc:
                        desc_lower = desc.lower()
                        for dept, keywords in dept_keywords.items():
                            if any(keyword in desc_lower for keyword in keywords):
                                departments.add(dept)

                b2b.department_interactions = len(departments)
            else:
                b2b.department_interactions = 0

    @api.depends('partner_id.purchase_ids.amount', 'partner_id.purchase_ids.purchase_date')
    def _compute_b2b_analytics(self):
        """Calculate B2B specific analytics"""
        for b2b in self:
            purchases = b2b.partner_id.purchase_ids
            if purchases:
                b2b.avg_order_value = sum(purchases.mapped('amount')) / len(purchases)

                if len(purchases) > 1:
                    purchase_dates = sorted(purchases.mapped('purchase_date'))
                    total_days = (purchase_dates[-1] - purchase_dates[0]).days
                    b2b.purchase_frequency_days = total_days / (len(purchases) - 1)
                else:
                    b2b.purchase_frequency_days = 0
            else:
                b2b.avg_order_value = 0.0
                b2b.purchase_frequency_days = 0.0

    # ====================================
    # CONSTRAINTS (same as before)
    # ====================================

    _sql_constraints = [
        ('unique_partner_b2b', 'UNIQUE(partner_id)',
         'Each partner can have only one B2B extension record.'),
        ('positive_contract_value', 'CHECK(contract_value >= 0)',
         'Contract value cannot be negative.'),
    ]

    @api.constrains('vat')
    def _check_vat_format(self):
        """Basic VAT format validation"""
        for b2b in self:
            if b2b.vat and len(b2b.vat.replace('-', '').replace(' ', '')) < 8:
                raise ValidationError(_("VAT number must be at least 8 characters long."))
