from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    customer_type = fields.Selection(
        [('cash', 'Cash Customer'), ('credit', 'Credit Customer')],
        string='Customer Type',
        default='cash',
        readonly=True
    )
    credit_approved = fields.Boolean(string="Credit Approved", default=False)
    credit_limit = fields.Float(string='Credit Limit', required=False)

    def open_credit_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'credit.limit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id}
        }

class ResUsers(models.Model):
    _inherit = 'res.users'

    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string="Allowed Warehouses"
    )