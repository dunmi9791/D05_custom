from odoo import models, fields, api, exceptions, _
import base64
import qrcode
import io
from odoo.exceptions import UserError

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    allowed_groups = fields.Many2many('res.groups', string="Allowed Groups")