# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, ValidationError
from odoo.osv.expression import AND, OR
from odoo.tools import float_round
from odoo.tools.misc import clean_context

from collections import defaultdict


class MrpBom(models.Model):
    """ Defines bills of material for a product or a product template """
    _name = 'mrp.bom'
    _description = 'Bill of Material'
    _inherit = ['mail.thread']
    _rec_name = 'product_tmpl_id'
    _rec_names_search = ['product_tmpl_id', 'code']
    _order = "sequence, id"
    _check_company_auto = True

    def _get_default_product_uom_id(self):
        return self.env['uom.uom'].search([], limit=1, order='id').id

    code = fields.Char('Reference')
    active = fields.Boolean('Active', default=True)
    type = fields.Selection([
        ('normal', 'Manufacture this product'),
        ('phantom', 'Kit')], 'BoM Type',
        default='normal', required=True)
    product_tmpl_id = fields.Many2one(
        'product.template', 'Product',
        check_company=True, index=True,
        domain="[('type', 'in', ['product', 'consu'])]", required=True)
    product_id = fields.Many2one(
        'product.product', 'Product Variant',
        check_company=True, index=True,
        domain="['&', ('product_tmpl_id', '=', product_tmpl_id), ('type', 'in', ['product', 'consu'])]",
        help="If a product variant is defined the BOM is available only for this product.")
    bom_line_ids = fields.One2many('mrp.bom.line', 'bom_id', 'BoM Lines', copy=True)
    byproduct_ids = fields.One2many('mrp.bom.byproduct', 'bom_id', 'By-products', copy=True)
    product_qty = fields.Float(
        'Quantity', default=1.0,
        digits='Product Unit of Measure', required=True,
        help="This should be the smallest quantity that this product can be produced in. If the BOM contains operations, make sure the work center capacity is accurate.")
    product_uom_id = fields.Many2one(
        'uom.uom', 'Unit of Measure',
        default=_get_default_product_uom_id, required=True,
        help="Unit of Measure (Unit of Measure) is the unit of measurement for the inventory control", domain="[('category_id', '=', product_uom_category_id)]")
    product_uom_category_id = fields.Many2one(related='product_tmpl_id.uom_id.category_id')
    sequence = fields.Integer('Sequence')
    operation_ids = fields.One2many('mrp.routing.workcenter', 'bom_id', 'Operations', copy=True)
    ready_to_produce = fields.Selection([
        ('all_available', ' When all components are available'),
        ('asap', 'When components for 1st operation are available')], string='Manufacturing Readiness',
        default='all_available', required=True)
    picking_type_id = fields.Many2one(
        'stock.picking.type', 'Operation Type', domain="[('code', '=', 'mrp_operation')]",
        check_company=True,
        help=u"When a procurement has a ‘produce’ route with a operation type set, it will try to create "
             "a Manufacturing Order for that product using a BoM of the same operation type. That allows "
             "to define stock rules which trigger different manufacturing orders with different BoMs.")
    company_id = fields.Many2one(
        'res.company', 'Company', index=True,
        default=lambda self: self.env.company)
    consumption = fields.Selection([
        ('flexible', 'Allowed'),
        ('warning', 'Allowed with warning'),
        ('strict', 'Blocked')],
        help="Defines if you can consume more or less components than the quantity defined on the BoM:\n"
             "  * Allowed: allowed for all manufacturing users.\n"
             "  * Allowed with warning: allowed for all manufacturing users with summary of consumption differences when closing the manufacturing order.\n"
             "  Note that in the case of component Manual Consumption, where consumption is registered manually exclusively, consumption warnings will still be issued when appropriate also.\n"
             "  * Blocked: only a manager can close a manufacturing order when the BoM consumption is not respected.",
        default='warning',
        string='Flexible Consumption',
        required=True
    )
    possible_product_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        compute='_compute_possible_product_template_attribute_value_ids')
    allow_operation_dependencies = fields.Boolean('Operation Dependencies',
        help="Create operation level dependencies that will influence both planning and the status of work orders upon MO confirmation. If this feature is ticked, and nothing is specified, Odoo will assume that all operations can be started simultaneously."
    )
    produce_delay = fields.Integer(
        'Manufacturing Lead Time', default=0,
        help="Average lead time in days to manufacture this product. In the case of multi-level BOM, the manufacturing lead times of the components will be added. In case the product is subcontracted, this can be used to determine the date at which components should be sent to the subcontractor.")
    days_to_prepare_mo = fields.Integer(
        string="Days to prepare Manufacturing Order", default=0,
        help="Create and confirm Manufacturing Orders this many days in advance, to have enough time to replenish components or manufacture semi-finished products.\n"
             "Note that security lead times will also be considered when appropriate.")

    _sql_constraints = [
        ('qty_positive', 'check (product_qty > 0)', 'The quantity to produce must be positive!'),
    ]

    @api.depends(
        'product_tmpl_id.attribute_line_ids.value_ids',
        'product_tmpl_id.attribute_line_ids.attribute_id.create_variant',
        'product_tmpl_id.attribute_line_ids.product_template_value_ids.ptav_active',
    )
    def _compute_possible_product_template_attribute_value_ids(self):
        for bom in self:
            bom.possible_product_template_attribute_value_ids = bom.product_tmpl_id.valid_product_template_attribute_line_ids._without_no_variant_attributes().product_template_value_ids._only_active()

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.bom_line_ids.bom_product_template_attribute_value_ids = False
            self.operation_ids.bom_product_template_attribute_value_ids = False
            self.byproduct_ids.bom_product_template_attribute_value_ids = False

    @api.constrains('active', 'product_id', 'product_tmpl_id', 'bom_line_ids')
    def _check_bom_cycle(self):
        subcomponents_dict = dict()

        def _check_cycle(components, finished_products):
            """
            Check whether the components are part of the finished products (-> cycle). Then, if
            these components have a BoM, repeat the operation with the subcomponents (recursion).
            The method will return the list of product variants that creates the cycle
            """
            products_to_find = self.env['product.product']

            for component in components:
                if component in finished_products:
                    names = finished_products.mapped('display_name')
                    raise ValidationError(_(
                        "The current configuration is incorrect because it would create a cycle between these products: %s.",
                        ', '.join(names)))
                if component not in subcomponents_dict:
                    products_to_find |= component

            bom_find_result = self._bom_find(products_to_find)
            for component in components:
                if component not in subcomponents_dict:
                    bom = bom_find_result[component]
                    subcomponents = bom.bom_line_ids.filtered(lambda l: not l._skip_bom_line(component)).product_id
                    subcomponents_dict[component] = subcomponents
                subcomponents = subcomponents_dict[component]
                if subcomponents:
                    _check_cycle(subcomponents, finished_products | component)

        boms_to_check = self
        domain = []
        for product in self.bom_line_ids.product_id:
            domain = OR([domain, self._bom_find_domain(product)])
        if domain:
            boms_to_check |= self.env['mrp.bom'].search(domain)

        for bom in boms_to_check:
            if not bom.active:
                continue
            finished_products = bom.product_id or bom.product_tmpl_id.product_variant_ids
            if bom.bom_line_ids.bom_product_template_attribute_value_ids:
                grouped_by_components = defaultdict(lambda: self.env['product.product'])
                for finished in finished_products:
                    components = bom.bom_line_ids.filtered(lambda l: not l._skip_bom_line(finished)).product_id
                    grouped_by_components[components] |= finished
                for components, finished in grouped_by_components.items():
                    _check_cycle(components, finished)
            else:
                _check_cycle(bom.bom_line_ids.product_id, finished_products)

    @api.constrains('product_id', 'product_tmpl_id', 'bom_line_ids', 'byproduct_ids', 'operation_ids')
    def _check_bom_lines(self):
        for bom in self:
            apply_variants = bom.bom_line_ids.bom_product_template_attribute_value_ids | bom.operation_ids.bom_product_template_attribute_value_ids | bom.byproduct_ids.bom_product_template_attribute_value_ids
            if bom.product_id and apply_variants:
                raise ValidationError(_("You cannot use the 'Apply on Variant' functionality and simultaneously create a BoM for a specific variant."))
            for ptav in apply_variants:
                if ptav.product_tmpl_id != bom.product_tmpl_id:
                    raise ValidationError(_(
                        "The attribute value %(attribute)s set on product %(product)s does not match the BoM product %(bom_product)s.",
                        attribute=ptav.display_name,
                        product=ptav.product_tmpl_id.display_name,
                        bom_product=bom.product_tmpl_id.display_name
                    ))
            for byproduct in bom.byproduct_ids:
                if bom.product_id:
                    same_product = bom.product_id == byproduct.product_id
                else:
                    same_product = bom.product_tmpl_id == byproduct.product_id.product_tmpl_id
                if same_product:
                    raise ValidationError(_("By-product %s should not be the same as BoM product.", bom.display_name))
                if byproduct.cost_share < 0:
                    raise ValidationError(_("By-products cost shares must be positive."))
            if sum(bom.byproduct_ids.mapped('cost_share')) > 100:
                raise ValidationError(_("The total cost share for a BoM's by-products cannot exceed 100."))

    @api.onchange('bom_line_ids', 'product_qty', 'product_id', 'product_tmpl_id')
    def onchange_bom_structure(self):
        if self.type == 'phantom' and self._origin and self.env['stock.move'].search([('bom_line_id', 'in', self._origin.bom_line_ids.ids)], limit=1):
            return {
                'warning': {
                    'title': _('Warning'),
                    'message': _(
                        'The product has already been used at least once, editing its structure may lead to undesirable behaviours. '
                        'You should rather archive the product and create a new one with a new bill of materials.'),
                }
            }

    @api.onchange('product_uom_id')
    def onchange_product_uom_id(self):
        res = {}
        if not self.product_uom_id or not self.product_tmpl_id:
            return
        if self.product_uom_id.category_id.id != self.product_tmpl_id.uom_id.category_id.id:
            self.product_uom_id = self.product_tmpl_id.uom_id.id
            res['warning'] = {'title': _('Warning'), 'message': _('The Product Unit of Measure you chose has a different category than in the product form.')}
        return res

    @api.onchange('product_tmpl_id')
    def onchange_product_tmpl_id(self):
        if self.product_tmpl_id:
            default_uom_id = self.env.context.get('default_product_uom_id')
            # Avoids updating the BoM's UoM in case a specific UoM was passed through as a default value.
            if self.product_uom_id.category_id != self.product_tmpl_id.uom_id.category_id or self.product_uom_id.id != default_uom_id:
                self.product_uom_id = self.product_tmpl_id.uom_id.id
            if self.product_id.product_tmpl_id != self.product_tmpl_id:
                self.product_id = False
            self.bom_line_ids.bom_product_template_attribute_value_ids = False
            self.operation_ids.bom_product_template_attribute_value_ids = False
            self.byproduct_ids.bom_product_template_attribute_value_ids = False

            domain = [('product_tmpl_id', '=', self.product_tmpl_id.id)]
            if self.id.origin:
                domain.append(('id', '!=', self.id.origin))
            number_of_bom_of_this_product = self.env['mrp.bom'].search_count(domain)
            if number_of_bom_of_this_product:  # add a reference to the bom if there is already a bom for this product
                self.code = _("%s (new) %s", self.product_tmpl_id.name, number_of_bom_of_this_product)

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        # Checks if the BoM was created from a Manufacturing Order (through Generate BoM action).
        parent_production_id = self.env.context.get('parent_production_id')
        if parent_production_id:  # In this case, assign the newly created BoM to the MO.
            # Clean context to avoid parasitic default values.
            self.env.context = clean_context(self.env.context)
            production = self.env['mrp.production'].browse(parent_production_id)
            production._link_bom(res[0])
        return res

    def write(self, vals):
        res = super().write(vals)
        relevant_fields = ['bom_line_ids', 'byproduct_ids', 'product_tmpl_id', 'product_id', 'product_qty']
        if any(field_name in vals for field_name in relevant_fields):
            self._set_outdated_bom_in_productions()
        if 'sequence' in vals and self and self[-1].id == list(self._prefetch_ids)[-1]:
            self.browse(self._prefetch_ids)._check_bom_cycle()
        return res

    def copy(self, default=None):
        res = super().copy(default)
        if self.operation_ids:
            operations_mapping = {}
            for original, copied in zip(self.operation_ids, res.operation_ids.sorted()):
                operations_mapping[original] = copied
            for bom_line in res.bom_line_ids:
                if bom_line.operation_id:
                    bom_line.operation_id = operations_mapping[bom_line.operation_id]
            for byproduct in res.byproduct_ids:
                if byproduct.operation_id:
                    byproduct.operation_id = operations_mapping[byproduct.operation_id]
            for operation in self.operation_ids:
                if operation.blocked_by_operation_ids:
                    copied_operation = operations_mapping[operation]
                    dependencies = []
                    for dependency in operation.blocked_by_operation_ids:
                        dependencies.append(Command.link(operations_mapping[dependency].id))
                    copied_operation.blocked_by_operation_ids = dependencies

        return res

    @api.model
    def name_create(self, name):
        # prevent to use string as product_tmpl_id
        if isinstance(name, str):
            key = 'default_' + self._rec_name
            if key in self.env.context:
                result = super().name_create(self.env.context[key])
                self.browse(result[0]).code = name
                return result
            raise UserError(_("You cannot create a new Bill of Material from here."))
        return super(MrpBom, self).name_create(name)

    def toggle_active(self):
        self.with_context({'active_test': False}).operation_ids.toggle_active()
        return super().toggle_active()

    @api.depends('code')
    def _compute_display_name(self):
        for bom in self:
            bom.display_name = f"{bom.code + ': ' if bom.code else ''}{bom.product_tmpl_id.display_name}"

    def action_compute_bom_days(self):
        company_id = self.env.context.get('default_company_id', self.env.company.id)
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company_id)], limit=1)
        for bom in self:
            bom_data = self.env['report.mrp.report_bom_structure'].with_context(minimized=True)._get_bom_data(bom, warehouse, bom.product_id, ignore_stock=True)
            bom.days_to_prepare_mo = self.env['report.mrp.report_bom_structure']._get_max_component_delay(bom_data['components'])
            if bom_data.get('availability_state') == 'unavailable' and not bom_data.get('components_available', True):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Cannot compute days to prepare due to missing route info for at least 1 component or for the final product.'),
                        'sticky': False,
                    }
                }

    @api.constrains('product_tmpl_id', 'product_id', 'type')
    def check_kit_has_not_orderpoint(self):
        product_ids = [pid for bom in self.filtered(lambda bom: bom.type == "phantom")
                           for pid in (bom.product_id.ids or bom.product_tmpl_id.product_variant_ids.ids)]
        if self.env['stock.warehouse.orderpoint'].search_count([('product_id', 'in', product_ids)], limit=1):
            raise ValidationError(_("You can not create a kit-type bill of materials for products that have at least one reordering rule."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_running_mo(self):
        if self.env['mrp.production'].search([('bom_id', 'in', self.ids), ('state', 'not in', ['done', 'cancel'])], limit=1):
            raise UserError(_('You can not delete a Bill of Material with running manufacturing orders.\nPlease close or cancel it first.'))

    @api.model
    def _bom_find_domain(self, products, picking_type=None, company_id=False, bom_type=False):
        domain = ['&', '|', ('product_id', 'in', products.ids), '&', ('product_id', '=', False), ('product_tmpl_id', 'in', products.product_tmpl_id.ids), ('active', '=', True)]
        if company_id or self.env.context.get('company_id'):
            domain = AND([domain, ['|', ('company_id', '=', False), ('company_id', '=', company_id or self.env.context.get('company_id'))]])
        if picking_type:
            domain = AND([domain, ['|', ('picking_type_id', '=', picking_type.id), ('picking_type_id', '=', False)]])
        if bom_type:
            domain = AND([domain, [('type', '=', bom_type)]])
        return domain

    @api.model
    def _bom_find(self, products, picking_type=None, company_id=False, bom_type=False):
        """ Find the first BoM for each products

        :param products: `product.product` recordset
        :return: One bom (or empty recordset `mrp.bom` if none find) by product (`product.product` record)
        :rtype: defaultdict(`lambda: self.env['mrp.bom']`)
        """
        bom_by_product = defaultdict(lambda: self.env['mrp.bom'])
        products = products.filtered(lambda p: p.type != 'service')
        if not products:
            return bom_by_product
        domain = self._bom_find_domain(products, picking_type=picking_type, company_id=company_id, bom_type=bom_type)

        # Performance optimization, allow usage of limit and avoid the for loop `bom.product_tmpl_id.product_variant_ids`
        if len(products) == 1:
            bom = self.search(domain, order='sequence, product_id, id', limit=1)
            if bom:
                bom_by_product[products] = bom
            return bom_by_product

        boms = self.search(domain, order='sequence, product_id, id')

        products_ids = set(products.ids)
        for bom in boms:
            products_implies = bom.product_id or bom.product_tmpl_id.product_variant_ids
            for product in products_implies:
                if product.id in products_ids and product not in bom_by_product:
                    bom_by_product[product] = bom

        return bom_by_product

    def explode(self, product, quantity, picking_type=False):
        """
            Explodes the BoM and creates two lists with all the information you need: bom_done and line_done
            Quantity describes the number of times you need the BoM: so the quantity divided by the number created by the BoM
            and converted into its UoM
        """
        product_ids = set()
        product_boms = {}
        def update_product_boms():
            products = self.env['product.product'].browse(product_ids)
            product_boms.update(self._bom_find(products, picking_type=picking_type or self.picking_type_id,
                company_id=self.company_id.id, bom_type='phantom'))
            # Set missing keys to default value
            for product in products:
                product_boms.setdefault(product, self.env['mrp.bom'])

        boms_done = [(self, {'qty': quantity, 'product': product, 'original_qty': quantity, 'parent_line': False})]
        lines_done = []

        bom_lines = []
        for bom_line in self.bom_line_ids:
            product_id = bom_line.product_id
            bom_lines.append((bom_line, product, quantity, False))
            product_ids.add(product_id.id)
        update_product_boms()
        product_ids.clear()
        while bom_lines:
            current_line, current_product, current_qty, parent_line = bom_lines[0]
            bom_lines = bom_lines[1:]

            if current_line._skip_bom_line(current_product):
                continue

            line_quantity = current_qty * current_line.product_qty
            if not current_line.product_id in product_boms:
                update_product_boms()
                product_ids.clear()
            bom = product_boms.get(current_line.product_id)
            if bom:
                converted_line_quantity = current_line.product_uom_id._compute_quantity(
                    line_quantity / bom.product_qty, bom.product_uom_id, round=False
                )
                bom_lines += [(line, current_line.product_id, converted_line_quantity, current_line) for line in bom.bom_line_ids]
                for bom_line in bom.bom_line_ids:
                    if not bom_line.product_id in product_boms:
                        product_ids.add(bom_line.product_id.id)
                boms_done.append((bom, {'qty': converted_line_quantity, 'product': current_product, 'original_qty': quantity, 'parent_line': current_line}))
            else:
                # We round up here because the user expects that if he has to consume a little more, the whole UOM unit
                # should be consumed.
                rounding = current_line.product_uom_id.rounding
                line_quantity = float_round(line_quantity, precision_rounding=rounding, rounding_method='UP')
                lines_done.append((current_line, {'qty': line_quantity, 'product': current_product, 'original_qty': quantity, 'parent_line': parent_line}))

        return boms_done, lines_done

    @api.model
    def get_import_templates(self):
        return [{
            'label': _('Import Template for Bills of Materials'),
            'template': '/mrp/static/xls/mrp_bom.xls'
        }]

    def _set_outdated_bom_in_productions(self):
        # Searches for MOs using these BoMs to notify them that their BoM has been updated.
        list_of_domain_by_bom = []
        for bom in self:
            domain_by_products = [('product_id', 'in', bom.product_tmpl_id.product_variant_ids.ids)]
            if bom.product_id:
                domain_by_products = [('product_id', '=', bom.product_id.id)]
            domain_for_confirmed_mo = AND([[('state', '=', 'confirmed')], domain_by_products])
            # Avoid confirmed MOs if the BoM's product was changed.
            domain_by_states = OR([[('state', '=', 'draft')], domain_for_confirmed_mo])
            list_of_domain_by_bom.append(AND([[('bom_id', '=', bom.id)], domain_by_states]))
        if list_of_domain_by_bom:
            domain = OR(list_of_domain_by_bom)
            productions = self.env['mrp.production'].search(domain)
            if productions:
                productions.is_outdated_bom = True


class MrpBomLine(models.Model):
    _name = 'mrp.bom.line'
    _order = "sequence, id"
    _rec_name = "product_id"
    _description = 'Bill of Material Line'
    _check_company_auto = True

    def _get_default_product_uom_id(self):
        return self.env['uom.uom'].search([], limit=1, order='id').id

    product_id = fields.Many2one('product.product', 'Component', required=True, check_company=True)
    product_tmpl_id = fields.Many2one('product.template', 'Product Template', related='product_id.product_tmpl_id', store=True, index=True)
    company_id = fields.Many2one(
        related='bom_id.company_id', store=True, index=True, readonly=True)
    product_qty = fields.Float(
        'Quantity', default=1.0,
        digits='Product Unit of Measure', required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', 'Product Unit of Measure',
        default=_get_default_product_uom_id,
        required=True,
        help="Unit of Measure (Unit of Measure) is the unit of measurement for the inventory control", domain="[('category_id', '=', product_uom_category_id)]")
    product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id')
    sequence = fields.Integer(
        'Sequence', default=1,
        help="Gives the sequence order when displaying.")
    bom_id = fields.Many2one(
        'mrp.bom', 'Parent BoM',
        index=True, ondelete='cascade', required=True)
    parent_product_tmpl_id = fields.Many2one('product.template', 'Parent Product Template', related='bom_id.product_tmpl_id')
    possible_bom_product_template_attribute_value_ids = fields.Many2many(related='bom_id.possible_product_template_attribute_value_ids')
    bom_product_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value', string="Apply on Variants", ondelete='restrict',
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        help="BOM Product Variants needed to apply this line.")
    allowed_operation_ids = fields.One2many('mrp.routing.workcenter', related='bom_id.operation_ids')
    operation_id = fields.Many2one(
        'mrp.routing.workcenter', 'Consumed in Operation', check_company=True,
        domain="[('id', 'in', allowed_operation_ids)]",
        help="The operation where the components are consumed, or the finished products created.")
    child_bom_id = fields.Many2one(
        'mrp.bom', 'Sub BoM', compute='_compute_child_bom_id')
    child_line_ids = fields.One2many(
        'mrp.bom.line', string="BOM lines of the referred bom",
        compute='_compute_child_line_ids')
    attachments_count = fields.Integer('Attachments Count', compute='_compute_attachments_count')
    tracking = fields.Selection(related='product_id.tracking')
    manual_consumption = fields.Boolean(
        'Manual Consumption', default=False, compute='_compute_manual_consumption',
        readonly=False, store=True, copy=True,
        help="When activated, then the registration of consumption for that component is recorded manually exclusively.\n"
             "If not activated, and any of the components consumption is edited manually on the manufacturing order, Odoo assumes manual consumption also.")
    manual_consumption_readonly = fields.Boolean(
        'Manual Consumption Readonly', compute='_compute_manual_consumption_readonly')

    _sql_constraints = [
        ('bom_qty_zero', 'CHECK (product_qty>=0)', 'All product quantities must be greater or equal to 0.\n'
            'Lines with 0 quantities can be used as optional lines. \n'
            'You should install the mrp_byproduct module if you want to manage extra products on BoMs!'),
    ]

    @api.depends('product_id', 'tracking', 'operation_id')
    def _compute_manual_consumption(self):
        for line in self:
            line.manual_consumption = (line.tracking != 'none' or line.operation_id)

    @api.depends('tracking', 'operation_id')
    def _compute_manual_consumption_readonly(self):
        for line in self:
            line.manual_consumption_readonly = (line.tracking != 'none' or line.operation_id)

    @api.depends('product_id', 'bom_id')
    def _compute_child_bom_id(self):
        products = self.product_id
        bom_by_product = self.env['mrp.bom']._bom_find(products)
        for line in self:
            if not line.product_id:
                line.child_bom_id = False
            else:
                line.child_bom_id = bom_by_product.get(line.product_id, False)

    @api.depends('product_id')
    def _compute_attachments_count(self):
        for line in self:
            nbr_attach = self.env['mrp.document'].search_count([
                '|',
                '&', ('res_model', '=', 'product.product'), ('res_id', '=', line.product_id.id),
                '&', ('res_model', '=', 'product.template'), ('res_id', '=', line.product_id.product_tmpl_id.id)])
            line.attachments_count = nbr_attach

    @api.depends('child_bom_id')
    def _compute_child_line_ids(self):
        """ If the BOM line refers to a BOM, return the ids of the child BOM lines """
        for line in self:
            line.child_line_ids = line.child_bom_id.bom_line_ids.ids or False

    @api.onchange('product_uom_id')
    def onchange_product_uom_id(self):
        res = {}
        if not self.product_uom_id or not self.product_id:
            return res
        if self.product_uom_id.category_id != self.product_id.uom_id.category_id:
            self.product_uom_id = self.product_id.uom_id.id
            res['warning'] = {'title': _('Warning'), 'message': _('The Product Unit of Measure you chose has a different category than in the product form.')}
        return res

    @api.onchange('product_id')
    def onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id.id

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if 'product_id' in values and 'product_uom_id' not in values:
                values['product_uom_id'] = self.env['product.product'].browse(values['product_id']).uom_id.id
        return super(MrpBomLine, self).create(vals_list)

    def _skip_bom_line(self, product):
        """ Control if a BoM line should be produced, can be inherited to add
        custom control.
        """
        self.ensure_one()
        if product._name == 'product.template':
            return False
        return not product._match_all_variant_values(self.bom_product_template_attribute_value_ids)

    def action_see_attachments(self):
        domain = [
            '|',
            '&', ('res_model', '=', 'product.product'), ('res_id', '=', self.product_id.id),
            '&', ('res_model', '=', 'product.template'), ('res_id', '=', self.product_id.product_tmpl_id.id)]
        attachment_view = self.env.ref('mrp.view_document_file_kanban_mrp')
        return {
            'name': _('Attachments'),
            'domain': domain,
            'res_model': 'mrp.document',
            'type': 'ir.actions.act_window',
            'view_id': attachment_view.id,
            'views': [(attachment_view.id, 'kanban'), (False, 'form')],
            'view_mode': 'kanban,tree,form',
            'help': _('''<p class="o_view_nocontent_smiling_face">
                        Upload files to your product
                    </p><p>
                        Use this feature to store any files, like drawings or specifications.
                    </p>'''),
            'limit': 80,
            'context': "{'default_res_model': '%s','default_res_id': %d, 'default_company_id': %s}" % ('product.product', self.product_id.id, self.company_id.id)
        }


class MrpByProduct(models.Model):
    _name = 'mrp.bom.byproduct'
    _description = 'Byproduct'
    _rec_name = "product_id"
    _check_company_auto = True
    _order = 'sequence, id'

    product_id = fields.Many2one('product.product', 'By-product', required=True, check_company=True)
    company_id = fields.Many2one(related='bom_id.company_id', store=True, index=True, readonly=True)
    product_qty = fields.Float(
        'Quantity',
        default=1.0, digits='Product Unit of Measure', required=True)
    product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id')
    product_uom_id = fields.Many2one('uom.uom', 'Unit of Measure', required=True,
                                     compute="_compute_product_uom_id", store=True, readonly=False, precompute=True,
                                     domain="[('category_id', '=', product_uom_category_id)]")
    bom_id = fields.Many2one('mrp.bom', 'BoM', ondelete='cascade', index=True)
    allowed_operation_ids = fields.One2many('mrp.routing.workcenter', related='bom_id.operation_ids')
    operation_id = fields.Many2one(
        'mrp.routing.workcenter', 'Produced in Operation', check_company=True,
        domain="[('id', 'in', allowed_operation_ids)]")
    possible_bom_product_template_attribute_value_ids = fields.Many2many(related='bom_id.possible_product_template_attribute_value_ids')
    bom_product_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value', string="Apply on Variants", ondelete='restrict',
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        help="BOM Product Variants needed to apply this line.")
    sequence = fields.Integer("Sequence")
    cost_share = fields.Float(
        "Cost Share (%)", digits=(5, 2),  # decimal = 2 is important for rounding calculations!!
        help="The percentage of the final production cost for this by-product line (divided between the quantity produced)."
             "The total of all by-products' cost share must be less than or equal to 100.")

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        """ Changes UoM if product_id changes. """
        for record in self:
            record.product_uom_id = record.product_id.uom_id.id

    def _skip_byproduct_line(self, product):
        """ Control if a byproduct line should be produced, can be inherited to add
        custom control.
        """
        self.ensure_one()
        if product._name == 'product.template':
            return False
        return not product._match_all_variant_values(self.bom_product_template_attribute_value_ids)
