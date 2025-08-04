from odoo import models, fields, api, exceptions, _
import base64
import qrcode
import io
from odoo.exceptions import UserError
from num2words import num2words  # Install this library if not available
import logging

_logger = logging.getLogger(__name__)

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    allowed_groups = fields.Many2many('res.groups', string="Allowed Groups")


class AccountMove(models.Model):
    _inherit = 'account.move'

    create_date_only = fields.Date(
        string="Creation Date (Date Only)",
        compute="_compute_create_date_only",
        store=True
    )
    customer_type = fields.Selection(
        string='Customer Type',
        related='partner_id.customer_type',
        store=True,  # Optional: Set to True if you want the field to be stored in the database
        readonly=True  # Optional: Set to True to make it read-only
    )

    @api.depends('create_date')
    def _compute_create_date_only(self):
        for record in self:
            record.create_date_only = record.create_date.date() if record.create_date else False






class AccountPayment(models.Model):
    _inherit = 'account.payment'

    create_date_only = fields.Date(
        string="Creation Date (Date Only)",
        compute="_compute_create_date_only",
        store=True
    )

    balance_before = fields.Float(
        string="Balance Before Payment",
        compute="_compute_balances",
        store=False,  # Non-stored for performance
    )
    balance_after = fields.Float(
        string="Balance After Payment",
        compute="_compute_balances",
        store=False,  # Non-stored for performance
    )
    amount_in_words = fields.Char(
        string="Amount in Words",
        compute="_compute_amount_in_words",
        store=True,  # Stored for reporting purposes
    )

    @api.depends('partner_id', 'amount', 'currency_id', 'date', 'state', 'payment_type')
    def _compute_balances(self):
        today = fields.Date.context_today(self)
        for payment in self:
            if payment.state != 'posted' or not payment.partner_id:
                payment.balance_before = payment.balance_after = 0.0
                continue

            cutoff = payment.date or today
            company_cur = payment.company_id.currency_id

            # only AR/AP, posted, unreconciled partner lines up to the payment date
            domain = [
                ('partner_id', '=', payment.partner_id.id),
                ('company_id', '=', payment.company_id.id),
                ('move_id.state', '=', 'posted'),
                ('full_reconcile_id', '=', False),
                ('date', '<=', cutoff),
                ('account_id.reconcile', '=', True),  # ← picks up both receivable & payable accounts
                ('account_id.non_trade', '=', False),  # ← your original non-trade filter
            ]
            lines = self.env['account.move.line'].search(domain)

            balance_before = sum(lines.mapped('balance'))

            amount_cc = payment.amount
            if payment.currency_id != company_cur:
                amount_cc = payment.currency_id._convert(
                    payment.amount, company_cur,
                    payment.company_id, cutoff
                )

            if payment.payment_type == 'inbound':  # customer → you
                balance_after = balance_before - amount_cc
            elif payment.payment_type == 'outbound':  # you → vendor
                balance_after = balance_before + amount_cc
            else:  # transfer or other
                balance_after = balance_before

            payment.balance_before = balance_before
            payment.balance_after = balance_after

    @api.depends('amount', 'currency_id')
    def _compute_amount_in_words(self):
        for payment in self:
            try:
                currency_name = payment.currency_id.name or 'Units'
                lang = self.env.user.lang or 'en'
                amount_words = num2words(payment.amount, lang=lang.split('_')[0]).capitalize()
                payment.amount_in_words = f"{amount_words} {currency_name}"
            except Exception:
                payment.amount_in_words = "Error converting amount to words"

    def format_with_currency(self, amount):
        """Helper method to format an amount with the currency symbol."""
        currency_symbol = self.currency_id.symbol or ''
        return f"{currency_symbol} {amount:,.2f}"

    @api.depends('create_date')
    def _compute_create_date_only(self):
        for record in self:
            record.create_date_only = record.create_date.date() if record.create_date else False