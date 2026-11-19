# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    pricelist_line_count = fields.Integer(compute='_compute_pricelist_line_count')

    def _compute_pricelist_line_count(self):
        counts = {
            pricelist.id: count
            for pricelist, count in self.env['product.pricelist.item']._read_group(
                [('pricelist_id', 'in', self.ids)],
                ['pricelist_id'],
                ['__count'],
            )
        }
        for pricelist in self:
            pricelist.pricelist_line_count = counts.get(pricelist.id, 0)

    def action_open_pricelist_lines(self):
        self.ensure_one()
        action = dict(self.env['ir.actions.act_window']._for_xml_id(
            'D05_custom.action_pricelist_lines'
        ))
        action['domain'] = [('pricelist_id', '=', self.id)]
        action['context'] = {
            'default_pricelist_id': self.id,
            'default_compute_price': 'fixed',
            'default_applied_on': '1_product',
            'default_base': 'list_price',
        }
        return action
