# -*- coding: utf-8 -*-
"""Floor checks for ``product.pricelist.item``.

Covered when the rule names a product or a variant:

* fixed price
* percentage (discount) price, computed from the current base
* formula price, computed from the current base, discount, surcharge,
  rounding, and margins

The computed price is evaluated at ``min_quantity`` (or 1 when that is 0),
in the product's unit of measure, on today's date, in the pricelist currency.
The product minimum is converted into that currency with today's rate.

Not covered on the rule itself (the sale order line still refuses the price):

* rules that apply to a category or to all products
* a later change in cost, in another pricelist used as the base, or in the
  currency rate after the rule was saved
* a base pricelist whose own rules change later

A minimum of zero on the product skips the check for that product.
"""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .price_floor import (
    SELLING_PRICE_GROUP_XMLIDS,
    convert_amount,
    floor_is_active,
    format_amount,
    price_below,
    user_has_any_group,
)


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    default_code = fields.Char(
        string='Internal Reference',
        compute='_compute_default_code',
        store=True,
        index=True,
        help="Product internal reference, kept on the line so the pricelist "
             "list can be searched without joining the product on every keystroke.",
    )

    @api.depends('product_id.default_code', 'product_tmpl_id.default_code', 'applied_on')
    def _compute_default_code(self):
        for item in self:
            if item.product_id:
                item.default_code = item.product_id.default_code
            elif item.product_tmpl_id:
                item.default_code = item.product_tmpl_id.default_code
            else:
                item.default_code = False

    def _d05_check_can_edit_lines(self):
        if user_has_any_group(self.env, SELLING_PRICE_GROUP_XMLIDS):
            return
        raise AccessError(_(
            "Only a sales price manager or an accountant can change pricelist lines."
        ))

    @api.model_create_multi
    def create(self, vals_list):
        self._d05_check_can_edit_lines()
        return super().create(vals_list)

    def write(self, vals):
        self._d05_check_can_edit_lines()
        return super().write(vals)

    def unlink(self):
        self._d05_check_can_edit_lines()
        return super().unlink()

    def _d05_products_for_floor(self):
        self.ensure_one()
        if self.applied_on == '0_product_variant' and self.product_id:
            return self.product_id
        if self.applied_on == '1_product' and self.product_tmpl_id:
            return self.product_tmpl_id.product_variant_ids
        return self.env['product.product']

    def _d05_check_price_floor(self):
        for item in self:
            products = item._d05_products_for_floor()
            if not products:
                continue
            quantity = item.min_quantity or 1.0
            date = fields.Datetime.now()
            currency = item.currency_id or self.env.company.currency_id
            company = item.company_id or self.env.company
            for product in products:
                if not floor_is_active(self.env, product.minimum_price):
                    continue
                price = item._compute_price(
                    product, quantity, product.uom_id, date, currency=currency,
                )
                minimum = convert_amount(
                    self.env,
                    product.minimum_price,
                    product.currency_id,
                    currency,
                    company,
                    fields.Date.context_today(item),
                )
                if price_below(self.env, price, minimum):
                    raise UserError(_(
                        "The pricelist price of %(product)s on %(pricelist)s "
                        "(%(company)s) would be %(price)s, which is below the "
                        "minimum price (%(minimum)s).",
                        product=product.display_name,
                        pricelist=item.pricelist_id.display_name,
                        company=item.company_id.name or _('All companies'),
                        price=format_amount(self.env, price, currency),
                        minimum=format_amount(self.env, minimum, currency),
                    ))

    @api.constrains(
        'applied_on', 'product_tmpl_id', 'product_id', 'min_quantity',
        'compute_price', 'fixed_price', 'percent_price', 'base', 'base_pricelist_id',
        'price_discount', 'price_surcharge', 'price_round',
        'price_min_margin', 'price_max_margin', 'currency_id',
    )
    def _d05_constrain_price_floor(self):
        self._d05_check_price_floor()
