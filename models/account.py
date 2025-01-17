from odoo import models, fields, api, exceptions, _
import base64
import qrcode
import io
from odoo.exceptions import UserError

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


