# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class InteractionHistory(models.Model):
    _name = 'interaction.history'
    _description = 'Customer Interaction History'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'interaction_type'
    _order = 'interaction_date desc, id desc'

    # ====================================
    # CORE FIELDS
    # ====================================

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, ondelete='cascade',
        tracking=True, help="Customer involved in this interaction")

    product_id = fields.Many2one(
        'product.product', string='Product',
        tracking=True, help="Product discussed or demonstrated")

    interaction_type = fields.Selection([
        ('call', 'Phone Call'),
        ('email', 'Email'),
        ('meeting', 'Meeting'),
        ('demo', 'Product Demo'),
        ('support', 'Support Request'),
        ('complaint', 'Complaint'),
        ('feedback', 'Feedback'),
        ('quote_request', 'Quote Request'),
        ('follow_up', 'Follow Up'),
        ('other', 'Other')
    ], string='Interaction Type', required=True, default='call', tracking=True)

    interaction_date = fields.Datetime(
        'Interaction Date', required=True, default=fields.Datetime.now, tracking=True)

    description = fields.Html('Description', required=True)

    user_id = fields.Many2one(
        'res.users', string='Sales Rep', required=True,
        default=lambda self: self.env.user, tracking=True)

    duration_minutes = fields.Integer('Duration (Minutes)')

    outcome = fields.Selection([
        ('positive', 'Positive'),
        ('neutral', 'Neutral'),
        ('negative', 'Negative'),
        ('follow_up_needed', 'Follow-up Needed')
    ], string='Outcome', default='neutral', tracking=True)

    next_action = fields.Text('Next Action')

    priority = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent')
    ], string='Priority', default='medium')

    # Related fields
    partner_customer_type = fields.Selection(
        related='partner_id.customer_type', string='Customer Type', readonly=True)

    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # ====================================
    # BUSINESS METHODS - BUTTON ACTIONS
    # ====================================

    def create_follow_up_interaction(self):
        """Create a follow-up interaction based on current one"""
        self.ensure_one()
        follow_up = self.copy({
            'interaction_type': 'follow_up',
            'interaction_date': fields.Datetime.now(),
            'description': f'<p>Follow-up from previous interaction on {self.interaction_date.strftime("%Y-%m-%d")}:</p>{self.description}',
            'outcome': 'neutral',
            'next_action': ''
        })

        return {
            'name': _('Follow-up Interaction'),
            'view_mode': 'form',
            'res_model': 'interaction.history',
            'res_id': follow_up.id,
            'type': 'ir.actions.act_window',
            'target': 'current'
        }

    def schedule_next_interaction(self):
        """Schedule next interaction as calendar event"""
        self.ensure_one()
        return {
            'name': _('Schedule Next Interaction'),
            'view_mode': 'form',
            'res_model': 'calendar.event',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': {
                'default_name': f'Follow-up with {self.partner_id.name}',
                'default_partner_ids': [(6, 0, [self.partner_id.id])],
                'default_description': f'Follow-up from interaction: {self.description[:100] if self.description else ""}...',
                'default_user_id': self.user_id.id,
            }
        }

    # ====================================
    # CRUD OVERRIDES
    # ====================================

    @api.model_create_multi
    def create(self, vals_list):
        """Update partner analytics when creating interactions"""
        interactions = super().create(vals_list)

        for interaction in interactions:
            if interaction.partner_id:
                interaction.partner_id._compute_analytics_fields()

        return interactions

    def write(self, vals):
        """Update partner analytics when modifying interactions"""
        result = super().write(vals)

        if 'interaction_date' in vals:
            partners_to_update = self.mapped('partner_id')
            for partner in partners_to_update:
                partner._compute_analytics_fields()

        return result

    def unlink(self):
        """Update partner analytics when deleting interactions"""
        partners_to_update = self.mapped('partner_id')
        result = super().unlink()

        for partner in partners_to_update:
            partner._compute_analytics_fields()

        return result

    # ====================================
    # CONSTRAINTS
    # ====================================

    @api.constrains('duration_minutes')
    def _check_duration(self):
        for interaction in self:
            if interaction.duration_minutes and interaction.duration_minutes < 0:
                raise ValidationError(_("Duration cannot be negative."))
            if interaction.duration_minutes and interaction.duration_minutes > 1440:
                raise ValidationError(_("Duration cannot exceed 24 hours (1440 minutes)."))
