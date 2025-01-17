from odoo import models, fields, api, _

class CreditLimitWizard(models.TransientModel):
    _name = 'credit.limit.wizard'
    _description = 'Credit Limit Wizard'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    credit_limit = fields.Float(string='Credit Limit', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id.id,
        required=True
    )

    def apply_credit(self):
        self.ensure_one()
        if not self.partner_id:
            raise ValueError(_("No customer selected!"))
        self.partner_id.write({
            'customer_type': 'credit',
            'credit_approved': True,
            'credit_limit': self.credit_limit,
        })
