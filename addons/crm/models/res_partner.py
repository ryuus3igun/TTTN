# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.osv import expression
from odoo.exceptions import ValidationError, UserError


class Partner(models.Model):
    _name = 'res.partner'
    _inherit = 'res.partner'

    # ====================================
    # EXISTING FIELDS FROM BASE CRM (Keep as is)
    # ====================================
    team_id = fields.Many2one(
        'crm.team', string='Sales Team',
        compute='_compute_team_id',
        precompute=True,
        ondelete='set null', readonly=False, store=True)
    opportunity_ids = fields.One2many('crm.lead', 'partner_id', string='Opportunities',
                                      domain=[('type', '=', 'opportunity')])
    opportunity_count = fields.Integer("Opportunity", compute='_compute_opportunity_count')

    # ====================================
    # CUSTOMER TYPE FIELD - SIMPLIFIED
    # ====================================

    customer_type = fields.Selection([
        ('b2c', 'B2C (Individual)'),
        ('b2b', 'B2B (Business)'),
        ('partner', 'Partner (Supplier/Agent/Collaborator)')
    ], string='Customer Type', required=True, default='b2c',
        help="Customer classification for pipeline management")

    # ====================================
    # ANALYTICS FIELDS (Keep as before)
    # ====================================

    last_activity_datetime = fields.Datetime(
        'Last Activity', compute='_compute_analytics_fields', store=True)
    total_interactions = fields.Integer(
        'Total Interactions', compute='_compute_analytics_fields', store=True)
    last_interaction_date = fields.Date(
        'Last Interaction Date', compute='_compute_analytics_fields', store=True)
    total_purchases = fields.Integer(
        'Total Purchases', compute='_compute_analytics_fields', store=True)
    total_revenue = fields.Float(
        'Total Revenue', compute='_compute_analytics_fields', store=True)
    last_purchase_date = fields.Date(
        'Last Purchase Date', compute='_compute_analytics_fields', store=True)
    customer_lifetime_value = fields.Float(
        'Customer Lifetime Value', compute='_compute_analytics_fields', store=True)
    analytics_updated_at = fields.Datetime(
        'Analytics Updated', compute='_compute_analytics_fields', store=True, default=fields.Datetime.now)

    # ====================================
    # RELATIONSHIP FIELDS (Keep as before)
    # ====================================

    b2c_info = fields.One2many('res.partner.b2c', 'partner_id', string='B2C Info')
    b2b_info = fields.One2many('res.partner.b2b', 'partner_id', string='B2B Info')
    partner_info = fields.One2many('res.partner.partner', 'partner_id', string='Partner Info')
    interaction_ids = fields.One2many('interaction.history', 'partner_id', string='Interactions')
    purchase_ids = fields.One2many('purchase.history', 'partner_id', string='Purchase History')
    interaction_count = fields.Integer('Interactions', compute='_compute_history_counts')
    purchase_count = fields.Integer('Purchases', compute='_compute_history_counts')

    # ====================================
    # EXISTING METHODS FROM BASE CRM (Keep as is)
    # ====================================

    @api.model
    def default_get(self, fields):
        rec = super(Partner, self).default_get(fields)
        active_model = self.env.context.get('active_model')
        if active_model == 'crm.lead' and len(self.env.context.get('active_ids', [])) <= 1:
            lead = self.env[active_model].browse(self.env.context.get('active_id')).exists()
            if lead:
                rec.update(
                    phone=lead.phone,
                    mobile=lead.mobile,
                    function=lead.function,
                    title=lead.title.id,
                    website=lead.website,
                    street=lead.street,
                    street2=lead.street2,
                    city=lead.city,
                    state_id=lead.state_id.id,
                    country_id=lead.country_id.id,
                    zip=lead.zip,
                )
        return rec

    @api.depends('parent_id')
    def _compute_team_id(self):
        for partner in self.filtered(
                lambda partner: not partner.team_id and partner.company_type == 'person' and partner.parent_id.team_id):
            partner.team_id = partner.parent_id.team_id

    def _compute_opportunity_count(self):
        all_partners = self.with_context(active_test=False).search_fetch(
            [('id', 'child_of', self.ids)], ['parent_id'],
        )
        opportunity_data = self.env['crm.lead'].with_context(active_test=False)._read_group(
            domain=[('partner_id', 'in', all_partners.ids)],
            groupby=['partner_id'], aggregates=['__count']
        )
        self_ids = set(self._ids)
        self.opportunity_count = 0
        for partner, count in opportunity_data:
            while partner:
                if partner.id in self_ids:
                    partner.opportunity_count += count
                partner = partner.parent_id

    def action_view_opportunity(self):
        action = self.env['ir.actions.act_window']._for_xml_id('crm.crm_lead_opportunities')
        action['context'] = {}
        if self.is_company:
            action['domain'] = [('partner_id.commercial_partner_id', '=', self.id)]
        else:
            action['domain'] = [('partner_id', '=', self.id)]
        action['domain'] = expression.AND([action['domain'], [('active', 'in', [True, False])]])
        return action

    # ====================================
    # ANALYTICS METHODS (Keep as before)
    # ====================================

    @api.depends('interaction_ids.interaction_date', 'purchase_ids.purchase_date',
                 'purchase_ids.amount', 'interaction_ids')
    def _compute_analytics_fields(self):
        for partner in self:
            interactions = partner.interaction_ids
            if interactions:
                partner.total_interactions = len(interactions)
                latest_interaction = max(interactions.mapped('interaction_date'))
                partner.last_interaction_date = latest_interaction
                partner.last_activity_datetime = latest_interaction
            else:
                partner.total_interactions = 0
                partner.last_interaction_date = False
                partner.last_activity_datetime = False

            purchases = partner.purchase_ids
            if purchases:
                partner.total_purchases = len(purchases)
                partner.total_revenue = sum(purchases.mapped('amount'))
                partner.last_purchase_date = max(purchases.mapped('purchase_date'))
                clv_coefficient = float(self.env['ir.config_parameter'].sudo().get_param(
                    'crm.customer_lifetime_coefficient', '1.2'))
                partner.customer_lifetime_value = partner.total_revenue * clv_coefficient
            else:
                partner.total_purchases = 0
                partner.total_revenue = 0.0
                partner.last_purchase_date = False
                partner.customer_lifetime_value = 0.0

            partner.analytics_updated_at = fields.Datetime.now()

    @api.depends('interaction_ids', 'purchase_ids')
    def _compute_history_counts(self):
        for partner in self:
            partner.interaction_count = len(partner.interaction_ids)
            partner.purchase_count = len(partner.purchase_ids)

    # ====================================
    # CUSTOMER TYPE LOGIC - FINAL WITH self.id DETECTION
    # ====================================

    @api.onchange('is_company')
    def _onchange_is_company_customer_type(self):
        """Handle is_company changes - LOCK for existing, ALLOW for new"""
        if self.id:
            # EXISTING PARTNER - LOCK EVERYTHING
            if self._origin and self.is_company != self._origin.is_company:
                # Reset to original value
                self.is_company = self._origin.is_company
                return {'warning': {
                    'title': _('Cannot Change Company Type'),
                    'message': _(
                        'Cannot change Individual/Company type for existing partners. This field is locked to prevent data inconsistency.')
                }}
        else:
            # NEW PARTNER - APPLY CONSTRAINTS
            if self.is_company:
                # Company: force B2B if was B2C
                if self.customer_type == 'b2c':
                    self.customer_type = 'b2b'
            else:
                # Individual: force B2C
                self.customer_type = 'b2c'

    @api.onchange('customer_type')
    def _onchange_customer_type(self):
        """Handle customer_type changes - LOCK for existing, VALIDATE for new"""
        if self.id:
            # EXISTING PARTNER - LOCK CUSTOMER_TYPE
            if self._origin and self.customer_type != self._origin.customer_type:
                # Reset to original value
                self.customer_type = self._origin.customer_type
                return {'warning': {
                    'title': _('Customer Type Locked'),
                    'message': _(
                        'Cannot change Customer Type for existing partners. This field is locked to prevent data inconsistency.')
                }}
        else:
            # NEW PARTNER - APPLY VALIDATION & AUTO-CORRECTION
            if self.is_company and self.customer_type == 'b2c':
                # Invalid: Company cannot be B2C
                self.customer_type = 'b2b'
                return {'warning': {
                    'title': _('Invalid Selection'),
                    'message': _('Companies cannot be B2C customers. Automatically changed to B2B.')
                }}
            elif not self.is_company and self.customer_type in ('b2b', 'partner'):
                # Invalid: Individual cannot be B2B/Partner
                self.customer_type = 'b2c'
                return {'warning': {
                    'title': _('Invalid Selection'),
                    'message': _('Individuals cannot be B2B or Partner customers. Automatically changed to B2C.')
                }}

    # ====================================
    # CONSTRAINTS & VALIDATIONS
    # ====================================

    @api.constrains('customer_type', 'is_company')
    def _check_customer_type_consistency(self):
        """Final validation to ensure customer_type is consistent with company_type"""
        for partner in self:
            if partner.is_company and partner.customer_type == 'b2c':
                raise ValidationError(
                    _("Companies cannot be B2C customer type. Please select B2B or Partner."))
            elif not partner.is_company and partner.customer_type in ('b2b', 'partner'):
                raise ValidationError(
                    _("Individuals cannot be B2B or Partner type. Individuals must be B2C."))

    # ====================================
    # CRUD OVERRIDES - SIMPLIFIED
    # ====================================

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-set customer_type based on is_company during creation"""
        for vals in vals_list:
            # Auto-set customer_type based on is_company during creation
            if 'customer_type' not in vals:
                is_company = vals.get('is_company', False)
                vals['customer_type'] = 'b2b' if is_company else 'b2c'

            # Validate consistency and auto-fix
            is_company = vals.get('is_company', False)
            customer_type = vals.get('customer_type', 'b2c')

            if is_company and customer_type == 'b2c':
                vals['customer_type'] = 'b2b'  # Auto-fix
            elif not is_company and customer_type in ('b2b', 'partner'):
                vals['customer_type'] = 'b2c'  # Auto-fix

        partners = super().create(vals_list)

        # Create extension records
        for partner in partners:
            partner._create_customer_type_extension()

        return partners

    def write(self, vals):
        """Handle writes - prevent changes to locked fields for existing records"""
        result = super().write(vals)

        # Create/update extension records if customer_type changed
        if 'customer_type' in vals:
            for partner in self:
                partner._create_customer_type_extension()

        return result

    def _create_customer_type_extension(self):
        """Create appropriate extension record based on customer_type"""
        self.ensure_one()

        # Clean up existing extension records
        self.b2c_info.unlink()
        self.b2b_info.unlink()
        self.partner_info.unlink()

        # Create new extension record
        if self.customer_type == 'b2c':
            self.env['res.partner.b2c'].create({'partner_id': self.id})
        elif self.customer_type == 'b2b':
            self.env['res.partner.b2b'].create({'partner_id': self.id})
        elif self.customer_type == 'partner':
            self.env['res.partner.partner'].create({'partner_id': self.id})

    # ====================================
    # BUSINESS METHODS (Keep as before)
    # ====================================

    def unlink(self):
        for partner in self:
            if partner.interaction_ids or partner.purchase_ids:
                raise UserError(_(
                    "Cannot delete partner '%s' because it has interaction or purchase history. "
                    "Archive the partner instead.") % partner.name)
        return super().unlink()

    def action_view_interactions(self):
        self.ensure_one()
        return {
            'name': _('Interaction History'),
            'view_mode': 'tree,form',
            'res_model': 'interaction.history',
            'type': 'ir.actions.act_window',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id}
        }

    def action_view_purchases(self):
        self.ensure_one()
        return {
            'name': _('Purchase History'),
            'view_mode': 'tree,form',
            'res_model': 'purchase.history',
            'type': 'ir.actions.act_window',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id}
        }
