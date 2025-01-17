from odoo import models, fields, api
from odoo.exceptions import UserError

class CustomOrderLineReport(models.TransientModel):
    _name = 'custom.order.line.report'
    _description = 'Custom Order Line Report'

    date = fields.Date(string="Date", required=True)

    def action_get_order_lines(self):
        if not self.date:
            raise UserError("Please select a date.")

        order_lines = self.env['sale.order.line'].search([
            ('create_date', '>=', self.date),
            ('create_date', '<', fields.Datetime.to_string(fields.Date.from_string(self.date) + timedelta(days=1)))
        ])

        action = self.env.ref('D05_custom.action_order_lines_report_list').read()[0]
        action['domain'] = [('id', 'in', order_lines.ids)]
        return action
