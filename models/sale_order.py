from odoo import models, fields, api, exceptions, _
import base64
import qrcode
import io
from odoo.exceptions import UserError
from odoo.exceptions import AccessError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    qr_code = fields.Binary("QR Code")
    create_date_only = fields.Date(
        string="Creation Date (Date Only)",
        compute="_compute_create_date_only",
        store=True
    )
    payment_type = fields.Selection(
        [('paid', 'Paid'), ('credit', 'Credit')],
        string='Payment Type',
        default='paid',
        tracking=True,
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

    @api.model
    def create(self, vals):
        # Restrict setting payment_type to 'credit' for unauthorized users
        if 'payment_type' in vals and vals['payment_type'] == 'credit' and not self.env.user.has_group(
                'account.group_account_manager'):
            raise AccessError("Only users in the Credit Control group can set a sale as a Credit Sale.")
        record = super(SaleOrder, self).create(vals)
        record.generate_qr_code()  # Generate QR code upon creation
        return record

    def write(self, vals):
        # Restrict updating payment_type to 'credit' for unauthorized users
        if 'payment_type' in vals and vals['payment_type'] == 'credit':
            if not self.env.user.has_group('account.group_account_manager'):
                raise AccessError("Only users in the Credit Control group can update the Payment Type to Credit Sale.")
        res = super(SaleOrder, self).write(vals)
        if 'qr_code' not in vals:  # Prevent infinite recursion
            self.generate_qr_code()  # Regenerate QR code on update
        return res

    def generate_qr_code(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for record in self:
            # Construct the URL for the sale order
            sale_order_url = f"{base_url}/web#id={record.id}&model=sale.order&view_type=form"

            # Generate the QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(sale_order_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')

            # Convert QR code image to base64 for storing in a Binary field
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue())
            record.sudo().write({'qr_code': img_str})

    def action_print_sales_docket(self):
        for order in self:
            # Ensure there are invoices associated with the sale order
            if not order.invoice_ids:
                raise UserError("This order cannot be printed because it has no invoices.")

            # Check if all invoices are posted
            if not all(invoice.state == 'posted' for invoice in order.invoice_ids):
                raise UserError("This order cannot be printed because not all invoices are fully posted.")

            # Check if all invoices are fully paid
            if not all(invoice.amount_residual == 0 for invoice in order.invoice_ids):
                raise UserError("This order cannot be printed because not all invoices are fully paid.")

        # Trigger the report if all conditions are met
        return self.env.ref('D05_custom.report_sales_order_docket').report_action(self)

    def _check_report_conditions(self):
        for order in self:
            if not order.invoice_ids:
                raise UserError("This order cannot be printed because it has no invoices.")
            if not all(invoice.state == 'posted' for invoice in order.invoice_ids):
                raise UserError("This order cannot be printed as all invoices are not fully posted.")
            if not all(invoice.amount_residual == 0 for invoice in order.invoice_ids):
                raise UserError("This order cannot be printed as all invoices are not fully paid.")

    def report_action(self, docids, data=None):
        self._check_report_conditions()
        return super(SaleOrder, self).report_action(docids, data)


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
                        not_paid_invoices = invoices.filtered(lambda inv: inv.payment_state not in ['paid', 'in_payment'] )
                        if not_paid_invoices:
                            raise UserError("You cannot validate the delivery because the invoice(s) are not fully paid.")
        # Proceed with the normal validation
        return super(StockPicking, self).button_validate()


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    list_price_readonly = fields.Float(
        string='Sale Price',
        compute='_compute_list_price_readonly',
    )
    list_price = fields.Float(
        tracking=True,  # Enable tracking on the sale price field
    )

    def _compute_list_price_readonly(self):
        for record in self:
            record.list_price_readonly = record.list_price



class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    product_qty_available = fields.Float(
        string='Available Quantity',
        compute='_compute_product_qty_available',
        store=False,
    )

    @api.depends('product_id', 'order_id.warehouse_id')
    def _compute_product_qty_available(self):
        for line in self:
            if line.product_id and line.order_id.warehouse_id:
                # Get the available quantity of the product for the specific warehouse
                qty_available = line.product_id.with_context(
                    warehouse=line.order_id.warehouse_id.id
                ).free_qty
                line.product_qty_available = qty_available
            else:
                line.product_qty_available = 0.0







