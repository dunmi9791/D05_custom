# -*- coding: utf-8 -*-

from . import controllers
from . import models
from . import wizards


def post_init_hook(env):
    """Populate minimum prices from the current sales price on a fresh install.

    Upgrades from an older version run the same function from
    ``migrations/17.0.1.1.0/post-migrate.py``. Both paths are idempotent and
    use SQL so existing below-floor orders and pricelist lines do not abort
    the install.
    """
    from odoo.addons.D05_custom.models.price_floor import populate_minimum_prices
    populate_minimum_prices(env)
