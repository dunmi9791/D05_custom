# -*- coding: utf-8 -*-
"""Shared helpers for the accountant's minimum selling price.

A minimum of zero means the product has no floor. Selling prices may then
be anything, including zero. An explicit zero is stored with
``minimum_price_initialized`` so the install/upgrade copy from ``list_price``
does not put a floor back later.
"""
from odoo.tools import float_compare, formatLang

# People who may set selling prices (catalog, pricelist, sale line) but not
# the floor. Accountants are included so they can raise a sales price when
# they need room for a higher minimum. Settings is included so the
# administrator is not locked out of the catalog.
SELLING_PRICE_GROUP_XMLIDS = (
    'base.group_system',
    'account.group_account_manager',
    'D05_custom.group_sales_order_price_manager',
    'D05_custom.group_price_manager',
)

# The floor itself. Billing Administrator is the accountant group already
# installed with Accounting. Settings can also set it. Credit Control implies
# Billing Administrator, so those users can set the floor too.
MINIMUM_PRICE_GROUP_XMLIDS = (
    'base.group_system',
    'account.group_account_manager',
)

# May edit a product in general (name, category, and so on). Price-manager
# groups are deliberately not in this list: they receive product write access
# only so they can change ``list_price``, and ``write`` rejects other fields
# unless the user is also in one of these groups.
PRODUCT_ADMIN_GROUP_XMLIDS = (
    'base.group_system',
    'account.group_account_manager',
    'sales_team.group_sale_manager',
    'stock.group_stock_manager',
)


def price_digits(env):
    return env['decimal.precision'].precision_get('Product Price')


def as_price(value):
    if value in (None, False):
        return 0.0
    return float(value)


def prices_differ(env, left, right):
    return float_compare(as_price(left), as_price(right), precision_digits=price_digits(env)) != 0


def price_below(env, amount, floor):
    return float_compare(as_price(amount), as_price(floor), precision_digits=price_digits(env)) < 0


def floor_is_active(env, amount):
    """Zero or less is "no floor", matching an explicit accountant choice."""
    return float_compare(as_price(amount), 0.0, precision_digits=price_digits(env)) > 0


def user_has_any_group(env, xmlids):
    if env.su:
        return True
    user = env.user
    return any(user.has_group(xmlid) for xmlid in xmlids)


def format_amount(env, amount, currency=None):
    if currency:
        return formatLang(env, as_price(amount), currency_obj=currency)
    return formatLang(env, as_price(amount), dp='Product Price')


def convert_amount(env, amount, from_currency, to_currency, company, date):
    if not from_currency or not to_currency or from_currency == to_currency:
        return as_price(amount)
    return from_currency._convert(as_price(amount), to_currency, company, date)


def populate_minimum_prices(env):
    """Copy ``list_price`` onto ``minimum_price`` once per product.

    Idempotent. Rows already initialized are left alone, including an
    explicit zero (no floor). A non-zero minimum that was never flagged is
    kept and then flagged, so a second run cannot overwrite it.

    Uses SQL on purpose. The ORM floor checks must not run here: existing
    pricelist items and sale lines may already sit under ``list_price``, and
    this upgrade has to install anyway.
    """
    env.cr.execute(
        """
        UPDATE product_template
           SET minimum_price = CASE
                   WHEN COALESCE(minimum_price, 0) = 0 THEN COALESCE(list_price, 0)
                   ELSE minimum_price
               END,
               minimum_price_initialized = TRUE
         WHERE minimum_price_initialized IS NOT TRUE
        """
    )
    env['product.template'].invalidate_model(['minimum_price', 'minimum_price_initialized'])
