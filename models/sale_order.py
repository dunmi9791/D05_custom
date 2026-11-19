from odoo import models, fields, api, exceptions, _
import base64
import qrcode
import io
from odoo.exceptions import UserError
from odoo.exceptions import AccessError
from odoo.tools import float_compare

from .price_floor import convert_amount, floor_is_active, format_amount, price_below, price_digits

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
        # Keep the pre-write prices so a line that is already under the floor
        # (an order saved before the floor moved) can still be edited, as long
        # as this save does not push it further below.
        orders = self
        if self.order_line:
            orders = self.with_context(**self.order_line._d05_snapshot_context())
        res = super(SaleOrder, orders).write(vals)
        if 'qr_code' not in vals:  # Prevent infinite recursion
            self.generate_qr_code()  # Regenerate QR code on update
        return res

    def _d05_net_and_floor(self):
        """Untaxed net against the sum of active minimums, in order currency.

        Discount-product lines count in the net (they are how a global or
        fixed discount is posted) and do not add a floor of their own.
        Returns and other negative quantities are left out: they are not a
        discount on the goods being sold.
        """
        self.ensure_one()
        net = 0.0
        floor = 0.0
        for line in self.order_line:
            if line.display_type or not line.product_id or line.is_downpayment:
                continue
            quantity = line.product_uom_qty or 0.0
            if quantity <= 0:
                continue
            net += line._d05_net_unit(line.price_unit, line.discount) * quantity
            if line._is_discount_line():
                continue
            minimum = line._d05_floor_in_line_currency()
            if floor_is_active(self.env, minimum):
                floor += minimum * quantity
        return net, floor

    def _d05_check_order_floor(self, previous_orders):
        digits = price_digits(self.env)
        for order in self:
            net, floor = order._d05_net_and_floor()
            if not floor_is_active(order.env, floor):
                continue
            if float_compare(net, floor, precision_digits=digits) >= 0:
                continue
            previous = previous_orders.get(order.id)
            if previous:
                old_shortfall = max((previous.get('floor') or 0.0) - (previous.get('net') or 0.0), 0.0)
                new_shortfall = floor - net
                if float_compare(new_shortfall, old_shortfall, precision_digits=digits) <= 0:
                    continue
            currency = order.currency_id
            raise UserError(_(
                "The net amount of %(order)s (%(net)s) cannot be lower than the "
                "minimum prices of its products (%(floor)s). A discount, on a "
                "line or on the order, cannot push the order under that floor.",
                order=order.display_name or _('this order'),
                net=format_amount(order.env, net, currency),
                floor=format_amount(order.env, floor, currency),
            ))

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
            # Get only non-cancelled invoices
            invoices = order.invoice_ids.filtered(lambda inv: inv.state != 'cancel')
            # Ensure there are invoices associated with the sale order
            if not invoices:
                raise UserError("This order cannot be printed because it has no invoices.")

            # Check if all invoices are posted
            if not all(invoice.state == 'posted' for invoice in invoices):
                raise UserError("This order cannot be printed because not all invoices are fully posted.")

            # Check if all invoices are fully paid
            if order.customer_type != 'credit':
                if not all(invoice.amount_residual == 0 for invoice in invoices):
                    raise UserError("This order cannot be printed because not all invoices are fully paid.")
            else:
                # Credit customers: outstanding balance must stay below the credit limit
                # (a limit of 0 means no limit)
                partner = order.partner_id.sudo()
                if partner.credit_limit and partner.outstanding_total >= partner.credit_limit:
                    raise UserError(_(
                        "This order cannot be printed because the customer's outstanding balance "
                        "(%(outstanding).2f) is not below their credit limit (%(limit).2f).",
                        outstanding=partner.outstanding_total,
                        limit=partner.credit_limit,
                    ))


        # Trigger the report if all conditions are met
        return self.env.ref('D05_custom.report_sales_order_docket').report_action(self)

    def _check_report_conditions(self):
        for order in self:
            invoices = order.invoice_ids.filtered(lambda inv: inv.state != 'cancel')
            if not invoices:
                raise UserError("This order cannot be printed because it has no invoices.")
            if not all(invoice.state == 'posted' for invoice in invoices):
                raise UserError("This order cannot be printed as all invoices are not fully posted.")
            if not all(invoice.amount_residual == 0 for invoice in invoices):
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
                            raise UserError(
                                "You cannot validate the delivery because the sale order has not been fully invoiced.")
                        # Check if the invoice is paid
                        invoices = sale_order.invoice_ids.filtered(lambda inv: inv.state != 'cancel')
                        if not invoices:
                            raise UserError(
                                "You cannot validate the delivery because there are no invoices linked to this sale order.")
                        # Check if all invoices are paid for non-credit customers
                        if sale_order.partner_id.customer_type != 'credit':
                            not_paid_invoices = invoices.filtered(
                                lambda inv: inv.payment_state not in ['paid', 'in_payment'])
                            if not_paid_invoices:
                                raise UserError(
                                    "You cannot validate the delivery because the invoice(s) are not fully paid.")

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


    def write(self, vals):
        lines = self.with_context(**self._d05_snapshot_context())
        return super(SaleOrderLine, lines).write(vals)

    def _d05_snapshot_context(self):
        """Capture prices before a write. The first snapshot in a save wins."""
        if self.env.context.get('d05_price_before') or not self:
            return {}
        return {'d05_price_before': self._d05_price_snapshot()}

    def _d05_price_snapshot(self):
        lines = {}
        for line in self:
            lines[line.id] = {
                'price_unit': line.price_unit,
                'discount': line.discount or 0.0,
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom.id,
            }
        orders = {}
        for order in self.order_id:
            net, floor = order._d05_net_and_floor()
            orders[order.id] = {'net': net, 'floor': floor}
        return {'lines': lines, 'orders': orders}

    def _d05_floor_in_line_currency(self):
        """Variant minimum expressed in this line's UoM and order currency.

        Zero means the product has no floor. Down payments and negative
        quantities (returns) are not floored.
        """
        self.ensure_one()
        if (
            not self.product_id
            or self.display_type
            or self.is_downpayment
            or self._is_discount_line()
            or (self.product_uom_qty or 0.0) < 0
        ):
            return 0.0
        product = self.product_id
        minimum = product.minimum_price
        if not floor_is_active(self.env, minimum):
            return 0.0
        uom = self.product_uom or product.uom_id
        if uom and product.uom_id and uom != product.uom_id:
            minimum = product.uom_id._compute_price(minimum, uom)
        currency = self.currency_id or self.order_id.currency_id
        company = self.order_id.company_id or self.company_id or self.env.company
        date = fields.Date.to_date(self.order_id.date_order) or fields.Date.context_today(self)
        return convert_amount(self.env, minimum, product.currency_id, currency, company, date)

    def _d05_net_unit(self, price_unit, discount):
        return (price_unit or 0.0) * (1.0 - (discount or 0.0) / 100.0)

    @api.constrains('price_unit', 'discount', 'product_id', 'product_uom', 'product_uom_qty')
    def _check_minimum_price(self):
        snapshot = self.env.context.get('d05_price_before') or {}
        line_snapshot = snapshot.get('lines') or {}
        for line in self:
            line._d05_check_line_floor(line_snapshot.get(line.id))
        self.order_id._d05_check_order_floor(snapshot.get('orders') or {})

    def _d05_check_line_floor(self, previous):
        self.ensure_one()
        minimum = self._d05_floor_in_line_currency()
        if not floor_is_active(self.env, minimum):
            return
        price_unit = self.price_unit or 0.0
        discount = self.discount or 0.0
        net = self._d05_net_unit(price_unit, discount)
        unit_low = price_below(self.env, price_unit, minimum)
        net_low = price_below(self.env, net, minimum)
        if not unit_low and not net_low:
            return
        # A line that was already under the floor can be saved when this edit
        # does not cut the unit price or the discounted price any further, and
        # does not move the line onto another product or unit of measure.
        if previous and previous.get('product_id') == self.product_id.id and previous.get('product_uom_id') == self.product_uom.id:
            old_unit = previous.get('price_unit') or 0.0
            old_net = self._d05_net_unit(old_unit, previous.get('discount') or 0.0)
            if not price_below(self.env, price_unit, old_unit) and not price_below(self.env, net, old_net):
                return
        currency = self.currency_id or self.order_id.currency_id
        if unit_low:
            raise UserError(_(
                "The unit price of %(product)s (%(unit)s) cannot be lower than "
                "the minimum price (%(minimum)s).",
                product=self.product_id.display_name,
                unit=format_amount(self.env, price_unit, currency),
                minimum=format_amount(self.env, minimum, currency),
            ))
        raise UserError(_(
            "The net price of %(product)s after the %(discount).2f%% discount "
            "(%(net)s) cannot be lower than the minimum price (%(minimum)s). "
            "The unit price is %(unit)s.",
            product=self.product_id.display_name,
            discount=discount,
            net=format_amount(self.env, net, currency),
            minimum=format_amount(self.env, minimum, currency),
            unit=format_amount(self.env, price_unit, currency),
        ))







