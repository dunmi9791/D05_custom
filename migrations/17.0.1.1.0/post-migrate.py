# -*- coding: utf-8 -*-
"""Upgrade hook for 17.0.1.1.0.

Copies ``list_price`` into ``minimum_price`` for products that do not already
have an initialized minimum. SQL, not the ORM, so sale orders and pricelist
items that are already under that price do not fail the upgrade.
"""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api
    from odoo.addons.D05_custom.models.price_floor import populate_minimum_prices

    env = api.Environment(cr, SUPERUSER_ID, {})
    populate_minimum_prices(env)
