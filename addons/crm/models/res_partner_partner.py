# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartnerPartner(models.Model):
    _name = 'res.partner.partner'
    _description = 'Partner Extension - Business Partner Information'
    _rec_name = 'partner_id'

    # ====================================
    # CORE FIELDS
    # ====================================

    partner_id = fields.Many2one(
        'res.partner', string='Partner', required=True, ondelete='cascade',
        domain="[('customer_type', '=', 'partner')]")

    # ====================================
    # SYSTEM FIELDS
    # ====================================

    create_at = fields.Datetime(
        'Created At', default=fields.Datetime.now, readonly=True,
        help="Timestamp when Partner information was created")

    # ====================================
    # PARTNER SPECIFIC FIELDS - MANUAL INPUT (same as before)
    # ====================================

    partner_type = fields.Selection([
        ('supplier', 'Supplier'),
        ('agent', 'Sales Agent'),
        ('collaborator', 'Collaborator')
    ], string='Partner Type', required=True, default='supplier',
        help="Type of business partnership relationship")

    partnership_start_date = fields.Date(
        'Partnership Start Date',
        help="Date when partnership relationship began")

    contract_end_date = fields.Date(
        'Contract End Date',
        help="Expiration date of current partnership contract")

    commission_rate = fields.Float(
        'Commission Rate (%)', digits=(5, 2),
        help="Commission percentage for sales agents")

    credit_limit = fields.Float(
        'Credit Limit',
        help="Maximum credit limit for suppliers")

    # ====================================
    # COMPUTED FIELDS (same as before)
    # ====================================

    shared_revenue = fields.Float(
        'Shared Revenue', compute='_compute_partnership_metrics', store=True,
        help="Total revenue generated through this partner relationship")

    collaboration_count = fields.Integer(
        'Successful Collaborations', compute='_compute_partnership_metrics', store=True,
        help="Count of successful opportunities/transactions linked to this partner")

    supplier_rank = fields.Integer(
        'Supplier Ranking', compute='_compute_supplier_rank', store=True,
        help="Ranking score based on delivery performance, quality, and reliability")

    partnership_duration_days = fields.Integer(
        'Partnership Duration (Days)', compute='_compute_partnership_analytics', store=True,
        help="Number of days since partnership started")

    avg_response_time_hours = fields.Float(
        'Avg Response Time (Hours)', compute='_compute_partnership_analytics', store=True,
        help="Average response time to inquiries and requests")

    # ====================================
    # COMPUTED METHODS (same as before - keeping all existing logic)
    # ====================================

    @api.depends('partner_id.purchase_ids.amount', 'commission_rate', 'partner_type')
    def _compute_partnership_metrics(self):
        """Calculate partnership performance metrics"""
        for partner_ext in self:
            if partner_ext.partner_id:
                total_revenue = sum(partner_ext.partner_id.purchase_ids.mapped('amount'))

                if partner_ext.partner_type == 'agent':
                    commission_rate = partner_ext.commission_rate or float(
                        self.env['ir.config_parameter'].sudo().get_param(
                            'crm.default_agent_commission_rate', '10.0'))
                    partner_ext.shared_revenue = total_revenue * (commission_rate / 100)
                elif partner_ext.partner_type == 'supplier':
                    partner_ext.shared_revenue = total_revenue
                else:  # collaborator
                    share_rate = float(self.env['ir.config_parameter'].sudo().get_param(
                        'crm.collaborator_revenue_share', '15.0'))
                    partner_ext.shared_revenue = total_revenue * (share_rate / 100)

                partner_ext.collaboration_count = len(partner_ext.partner_id.purchase_ids)
            else:
                partner_ext.shared_revenue = 0.0
                partner_ext.collaboration_count = 0

    @api.depends('partner_id.total_revenue', 'partner_id.total_interactions',
                 'partner_id.purchase_ids', 'partner_type')
    def _compute_supplier_rank(self):
        """Calculate supplier ranking based on multiple performance indicators"""
        for partner_ext in self:
            if partner_ext.partner_id and partner_ext.partner_type == 'supplier':
                base_score = 0

                revenue_score = min(40, partner_ext.partner_id.total_revenue / 10000)
                base_score += revenue_score

                interaction_score = min(30, partner_ext.partner_id.total_interactions * 2)
                base_score += interaction_score

                if partner_ext.partner_id.purchase_ids:
                    purchase_months = len(set(
                        p.purchase_date.strftime('%Y-%m')
                        for p in partner_ext.partner_id.purchase_ids
                    ))
                    consistency_score = min(20, purchase_months * 2)
                    base_score += consistency_score

                if partner_ext.partnership_start_date:
                    days = (fields.Date.today() - partner_ext.partnership_start_date).days
                    duration_score = min(10, days / 365 * 2)
                    base_score += duration_score

                partner_ext.supplier_rank = int(min(100, base_score))
            else:
                partner_ext.supplier_rank = 0

    @api.depends('partnership_start_date', 'partner_id.interaction_ids.interaction_date')
    def _compute_partnership_analytics(self):
        """Calculate partnership analytics"""
        for partner_ext in self:
            if partner_ext.partnership_start_date:
                partner_ext.partnership_duration_days = (
                        fields.Date.today() - partner_ext.partnership_start_date
                ).days
            else:
                partner_ext.partnership_duration_days = 0

            interactions = partner_ext.partner_id.interaction_ids
            if len(interactions) > 1:
                interaction_dates = sorted(interactions.mapped('interaction_date'))
                total_hours = 0
                for i in range(1, len(interaction_dates)):
                    diff = (interaction_dates[i] - interaction_dates[i - 1]).total_seconds() / 3600
                    total_hours += diff
                partner_ext.avg_response_time_hours = total_hours / (len(interaction_dates) - 1)
            else:
                partner_ext.avg_response_time_hours = 0.0

    # ====================================
    # BUSINESS METHODS (same as before)
    # ====================================

    def renew_partnership_contract(self):
        """Business method to renew partnership contract"""
        self.ensure_one()
        if self.contract_end_date:
            new_end_date = self.contract_end_date.replace(year=self.contract_end_date.year + 1)
            self.contract_end_date = new_end_date

            self.partner_id.message_post(
                body=_("Partnership contract renewed until %s") % new_end_date,
                subject=_("Contract Renewal")
            )
        return True

    # ====================================
    # CONSTRAINTS (same as before)
    # ====================================

    _sql_constraints = [
        ('unique_partner_partner', 'UNIQUE(partner_id)',
         'Each partner can have only one Partner extension record.'),
        ('positive_commission_rate', 'CHECK(commission_rate >= 0 AND commission_rate <= 100)',
         'Commission rate must be between 0 and 100 percent.'),
        ('positive_credit_limit', 'CHECK(credit_limit >= 0)',
         'Credit limit cannot be negative.'),
    ]

    @api.constrains('partnership_start_date', 'contract_end_date')
    def _check_partnership_dates(self):
        """Validate partnership and contract dates"""
        for partner_ext in self:
            if (partner_ext.partnership_start_date and
                    partner_ext.contract_end_date and
                    partner_ext.partnership_start_date > partner_ext.contract_end_date):
                raise ValidationError(_(
                    "Partnership start date cannot be later than contract end date."))
