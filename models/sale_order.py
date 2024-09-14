from odoo import models, fields, api
import base64
import qrcode
import io
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    qr_code = fields.Binary("QR Code")

    @api.model
    def create(self, vals):
        record = super(SaleOrder, self).create(vals)
        record.generate_qr_code()
        return record

    def write(self, vals):
        res = super(SaleOrder, self).write(vals)
        if 'qr_code' not in vals:  # Ensure this doesn't trigger infinite loop
            self.generate_qr_code()
        return res

    def generate_qr_code(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for record in self:
            # Construct the back-end URL to the sale order
            sale_order_url = f"{base_url}/web#id={record.id}&model=sale.order&view_type=form"

            # Generate QR code with the URL
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(sale_order_url)
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue())
            record.sudo().write({'qr_code': img_str})

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        # Check if the picking is related to a sale order
        for picking in self:
            if picking.picking_type_id.code == 'outgoing':
                sale_orders = picking.mapped('sale_id')
                if sale_orders:
                    for sale_order in sale_orders:
                        if sale_order.invoice_status != 'invoiced':
                            raise UserError("You cannot validate the delivery because the sale order has not been fully invoiced.")
                        # Check if the invoice is paid
                        invoices = sale_order.invoice_ids.filtered(lambda inv: inv.state != 'cancel')
                        if not invoices:
                            raise UserError("You cannot validate the delivery because there are no invoices linked to this sale order.")
                        # Check if all invoices are paid
                        not_paid_invoices = invoices.filtered(lambda inv: inv.payment_state != 'paid')
                        if not_paid_invoices:
                            raise UserError("You cannot validate the delivery because the invoice(s) are not fully paid.")
        # Proceed with the normal validation
        return super(StockPicking, self).button_validate()
