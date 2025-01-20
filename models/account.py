from odoo import models, fields, api, exceptions, _
import base64
import qrcode
import io
from odoo.exceptions import UserError
from num2words import num2words  # Install this library if not available

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

    @api.depends('create_date')
    def _compute_create_date_only(self):
        for record in self:
            record.create_date_only = record.create_date.date() if record.create_date else False




class AccountPayment(models.Model):
    _inherit = 'account.payment'

    balance_before = fields.Float(string="Balance Before Payment", compute="_compute_balances", store=True)
    balance_after = fields.Float(string="Balance After Payment", compute="_compute_balances", store=True)
    amount_in_words = fields.Char(string="Amount in Words", compute="_compute_amount_in_words", store=True)

    @api.depends('amount', 'partner_id')
    def _compute_balances(self):
        for payment in self:
            partner_ledger = self.env['account.move.line'].search([
                ('partner_id', '=', payment.partner_id.id),
                ('account_id.reconcile', '=', True)
            ])
            balance = sum(ledger.debit - ledger.credit for ledger in partner_ledger)
            payment.balance_before = balance
            payment.balance_after = balance + payment.amount

    @api.depends('amount', 'currency_id')
    def _compute_amount_in_words(self):
        for payment in self:
            currency_name = payment.currency_id.name or ''
            amount_words = num2words(payment.amount, lang='en').capitalize()
            payment.amount_in_words = f"{amount_words} {currency_name}"

    def format_with_currency(self, amount):
        """Helper method to format an amount with the currency symbol."""
        currency_symbol = self.currency_id.symbol or ''
        return f"{currency_symbol} {amount:,.2f}"


