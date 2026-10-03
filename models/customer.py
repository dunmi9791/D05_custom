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
    outstanding_total = fields.Monetary(
        string='Outstanding Total',
        compute='_compute_credit_overview',
        currency_field='currency_id',
        help="Unpaid balance of the customer's posted invoices, net of credit notes.",
    )
    last_order_ids = fields.Many2many(
        'sale.order',
        string='Last 3 Orders',
        compute='_compute_credit_overview',
    )
    last_payment_ids = fields.Many2many(
        'account.payment',
        string='Last 3 Payments',
        compute='_compute_credit_overview',
        groups='account.group_account_invoice',
    )

    def _compute_credit_overview(self):
        can_see_payments = self.env.user.has_group('account.group_account_invoice')
        for partner in self:
            commercial = partner.commercial_partner_id
            if not commercial.id:
                partner.outstanding_total = 0.0
                partner.last_order_ids = False
                if can_see_payments:
                    partner.last_payment_ids = False
                continue
            domain_partner = [('partner_id', 'child_of', commercial.id)]

            invoices = self.env['account.move'].search(domain_partner + [
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', '=', 'posted'),
                ('payment_state', 'not in', ('paid', 'reversed')),
            ])
            partner.outstanding_total = sum(invoices.mapped('amount_residual_signed'))

            partner.last_order_ids = self.env['sale.order'].search(
                domain_partner + [('state', '=', 'sale')],
                order='date_order desc, id desc', limit=3,
            )

            if can_see_payments:
                partner.last_payment_ids = self.env['account.payment'].search(
                    domain_partner + [
                        ('partner_type', '=', 'customer'),
                        ('payment_type', '=', 'inbound'),
                        ('state', '=', 'posted'),
                    ],
                    order='date desc, id desc', limit=3,
                )

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