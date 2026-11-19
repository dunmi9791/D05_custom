# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

from .price_floor import (
    MINIMUM_PRICE_GROUP_XMLIDS,
    PRODUCT_ADMIN_GROUP_XMLIDS,
    SELLING_PRICE_GROUP_XMLIDS,
    as_price,
    floor_is_active,
    format_amount,
    price_below,
    price_digits,
    prices_differ,
    user_has_any_group,
)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    minimum_price = fields.Float(
        string='Minimum Price',
        digits='Product Price',
        tracking=True,
        default=0.0,
        help="Lowest selling price an accountant allows for this product. "
             "Sales prices, pricelist prices, and discounted order lines cannot "
             "go below it. Zero means there is no floor.",
    )
    minimum_price_initialized = fields.Boolean(
        string='Minimum Price Initialized',
        default=False,
        copy=True,
        help="Set when the upgrade copied the sales price, or when an accountant "
             "saved a minimum (including zero). Keeps that choice from being "
             "overwritten if the copy runs again.",
    )

    def _d05_can_set_minimum(self):
        return user_has_any_group(self.env, MINIMUM_PRICE_GROUP_XMLIDS)

    def _d05_can_set_selling_price(self):
        return user_has_any_group(self.env, SELLING_PRICE_GROUP_XMLIDS)

    def _d05_is_product_admin(self):
        return user_has_any_group(self.env, PRODUCT_ADMIN_GROUP_XMLIDS)

    def _d05_check_price_permissions(self, vals, creating=False):
        """Block the wrong role from moving the floor or the sales price.

        Creating a product may set the initial sales price: there is no
        previous price to protect, and product creation stays with the
        existing product managers. Changing it afterwards is limited to
        price managers and accountants.
        """
        if self.env.su:
            return
        if 'minimum_price' in vals and not self._d05_can_set_minimum():
            changed = creating or any(
                prices_differ(self.env, vals['minimum_price'], template.minimum_price)
                for template in self
            )
            if changed:
                product = self[:1].display_name or _('this product')
                raise AccessError(_(
                    "Only an accountant (Billing Administrator) can set the minimum "
                    "price of %(product)s.",
                    product=product,
                ))
        if self and 'list_price' in vals and not self._d05_can_set_selling_price():
            changed = self.filtered(
                lambda template: prices_differ(self.env, vals['list_price'], template.list_price)
            )
            if changed:
                raise AccessError(_(
                    "Only a sales price manager or an accountant can change the sales "
                    "price of %(product)s.",
                    product=', '.join(changed.mapped('display_name')),
                ))
        if self and not self._d05_is_product_admin():
            extra = set(vals) - {'list_price'}
            if extra:
                raise AccessError(_(
                    "You can change the sales price, but not other product fields (%(fields)s).",
                    fields=', '.join(sorted(extra)),
                ))

    def _d05_price_gap(self, list_price, minimum):
        if not floor_is_active(self.env, minimum):
            return 0.0
        return as_price(minimum) - as_price(list_price)

    def _d05_check_floor_after_price_change(self, previous, creating=False):
        """Refuse a change that opens a wider gap under the floor.

        Products that were already below the floor (for example a pricelist
        copied before this module, or a floor loaded by SQL on upgrade) can
        still be saved. The gap between sales price and minimum is not
        allowed to grow. Pricelist lines are rechecked only when the sales
        price drops or the floor rises, which is what can push a percentage
        or formula under the floor.
        """
        digits = price_digits(self.env)
        for template in self:
            old_list, old_min = previous.get(
                template.id, (template.list_price, template.minimum_price)
            )
            old_gap = template._d05_price_gap(old_list, old_min)
            new_gap = template._d05_price_gap(template.list_price, template.minimum_price)
            if float_compare(new_gap, max(old_gap, 0.0), precision_digits=digits) > 0:
                raise UserError(_(
                    "The sales price of %(product)s (%(price)s) cannot be lower than "
                    "its minimum price (%(minimum)s). Raise the sales price, or set "
                    "a lower minimum.",
                    product=template.display_name,
                    price=format_amount(self.env, template.list_price, template.currency_id),
                    minimum=format_amount(self.env, template.minimum_price, template.currency_id),
                ))
            if not floor_is_active(self.env, template.minimum_price):
                continue
            list_dropped = price_below(self.env, template.list_price, old_list)
            floor_raised = price_below(self.env, old_min, template.minimum_price)
            if creating or list_dropped or floor_raised:
                template._d05_check_pricelist_items_against_floor()

    def _d05_check_pricelist_items_against_floor(self):
        """Reject a higher floor or a lower sales price that existing rules would break.

        Category-wide and global rules are not scanned here. A single fixed
        price cannot be compared with every product, and walking the catalog
        on each save would be slow. Those rules are enforced when a sale
        order line takes the computed price.
        """
        items = self.env['product.pricelist.item'].sudo().search([
            '|',
            ('product_tmpl_id', 'in', self.ids),
            ('product_id', 'in', self.mapped('product_variant_ids').ids),
        ])
        items._d05_check_price_floor()

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            self._d05_check_price_permissions(vals, creating=True)
            if 'minimum_price' in vals:
                vals['minimum_price_initialized'] = True
            prepared.append(vals)
        records = super().create(prepared)
        records._d05_check_floor_after_price_change(
            {record.id: (0.0, 0.0) for record in records},
            creating=True,
        )
        return records

    def write(self, vals):
        vals = dict(vals)
        self._d05_check_price_permissions(vals)
        if 'minimum_price' in vals:
            vals['minimum_price_initialized'] = True
        previous = {}
        if 'list_price' in vals or 'minimum_price' in vals:
            previous = {
                template.id: (template.list_price, template.minimum_price)
                for template in self
            }
        result = super().write(vals)
        if previous:
            self._d05_check_floor_after_price_change(previous)
        return result


class ProductProduct(models.Model):
    _inherit = 'product.product'

    minimum_price = fields.Float(
        string='Minimum Price',
        digits='Product Price',
        compute='_compute_minimum_price',
        help="Template minimum plus this variant's extra price. "
             "A template minimum of zero means the variant has no floor, "
             "whatever the extra price is.",
    )

    @api.depends('product_tmpl_id.minimum_price', 'price_extra')
    def _compute_minimum_price(self):
        for product in self:
            template_minimum = product.product_tmpl_id.minimum_price
            if not floor_is_active(product.env, template_minimum):
                product.minimum_price = 0.0
            else:
                product.minimum_price = template_minimum + (product.price_extra or 0.0)
