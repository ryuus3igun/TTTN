# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class ResPartnerB2C(models.Model):
    _name = 'res.partner.b2c'
    _description = 'Partner B2C Extension - Individual Customer Information'
    _rec_name = 'partner_id'

    # ====================================
    # CORE FIELDS
    # ====================================

    partner_id = fields.Many2one(
        'res.partner', string='Partner', required=True, ondelete='cascade',
        domain="[('customer_type', '=', 'b2c')]")

    # ====================================
    # SYSTEM FIELDS
    # ====================================

    create_at = fields.Datetime(
        'Created At', default=fields.Datetime.now, readonly=True,
        help="Timestamp when B2C information was created")

    # ====================================
    # B2C SPECIFIC FIELDS - MANUAL INPUT
    # ====================================

    personal_preference = fields.Text(
        'Personal Preferences',
        help="Customer preferences, interests, buying patterns, lifestyle notes")

    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender')

    birth_date = fields.Date(
        'Date of Birth',
        help="Customer's birth date for age-based marketing and birthday campaigns")

    # ====================================
    # COMPUTED FIELDS - SYSTEM DERIVED
    # ====================================

    loyalty_points = fields.Integer(
        'Loyalty Points', compute='_compute_loyalty_points', store=True,
        help="Loyalty points: +1 point per 100,000 VND spent. Automatically calculated from purchases.")

    # Additional computed fields for B2C analytics
    age = fields.Integer(
        'Age', compute='_compute_age',
        help="Current age calculated from birth date")

    age_group = fields.Selection([
        ('18-25', '18-25 years'),
        ('26-35', '26-35 years'),
        ('36-45', '36-45 years'),
        ('46-55', '46-55 years'),
        ('56+', '56+ years')
    ], string='Age Group', compute='_compute_age', store=True,
        help="Age group classification for marketing segmentation")

    # ====================================
    # COMPUTED METHODS
    # ====================================

    @api.depends('partner_id.purchase_ids.amount')
    def _compute_loyalty_points(self):
        """Calculate loyalty points: 1 point per 100,000 VND spent"""
        for b2c in self:
            if b2c.partner_id and b2c.partner_id.purchase_ids:
                total_spent = sum(b2c.partner_id.purchase_ids.mapped('amount'))
                # Get loyalty rate from system parameters (default 100,000 VND per point)
                point_rate = float(self.env['ir.config_parameter'].sudo().get_param(
                    'crm.b2c_loyalty_rate', '100000'))
                b2c.loyalty_points = int(total_spent / point_rate) if point_rate > 0 else 0
            else:
                b2c.loyalty_points = 0

    @api.depends('birth_date')
    def _compute_age(self):
        """Calculate current age and age group"""
        today = fields.Date.context_today(self)
        for b2c in self:
            if b2c.birth_date:
                b2c.age = today.year - b2c.birth_date.year
                if today.month < b2c.birth_date.month or \
                        (today.month == b2c.birth_date.month and today.day < b2c.birth_date.day):
                    b2c.age -= 1

                # Classify age group
                if 18 <= b2c.age <= 25:
                    b2c.age_group = '18-25'
                elif 26 <= b2c.age <= 35:
                    b2c.age_group = '26-35'
                elif 36 <= b2c.age <= 45:
                    b2c.age_group = '36-45'
                elif 46 <= b2c.age <= 55:
                    b2c.age_group = '46-55'
                elif b2c.age >= 56:
                    b2c.age_group = '56+'
                else:
                    b2c.age_group = False
            else:
                b2c.age = 0
                b2c.age_group = False

    # ====================================
    # CONSTRAINTS
    # ====================================

    _sql_constraints = [
        ('unique_partner_b2c', 'UNIQUE(partner_id)',
         'Each partner can have only one B2C extension record.'),
        ('positive_loyalty_points', 'CHECK(loyalty_points >= 0)',
         'Loyalty points cannot be negative.'),
    ]
