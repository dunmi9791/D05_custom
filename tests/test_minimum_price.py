# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged, TransactionCase

from odoo.addons.D05_custom.models.price_floor import populate_minimum_prices


@tagged('post_install', '-at_install')
class TestMinimumPrice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Floor Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'Floor Product',
            'list_price': 100.0,
            'detailed_type': 'consu',
        })
        cls.template = cls.product.product_tmpl_id
        cls.template.minimum_price = 80.0
        cls.accountant = cls._make_user('d05_accountant', 'account.group_account_manager')
        cls.order_price_manager = cls._make_user(
            'd05_so_price_mgr', 'D05_custom.group_sales_order_price_manager',
        )
        cls.sales_price_manager = cls._make_user(
            'd05_sales_price_mgr', 'D05_custom.group_price_manager',
        )
        cls.sales_admin = cls._make_user('d05_sales_admin', 'sales_team.group_sale_manager')
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'Floor Test Pricelist',
            'discount_policy': 'with_discount',
        })

    @classmethod
    def _make_user(cls, login, group_xmlid):
        groups = cls.env.ref('base.group_user') | cls.env.ref(group_xmlid)
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@d05.test' % login,
            'groups_id': [(6, 0, groups.ids)],
        })

    def _order(self, pricelist=None):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'pricelist_id': (pricelist or self.pricelist).id,
        })

    def _line(self, order, product=None, quantity=1.0):
        return self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': (product or self.product).id,
            'product_uom_qty': quantity,
        })

    def test_accountant_sets_minimum_and_manager_cannot(self):
        self.template.with_user(self.accountant).write({'minimum_price': 70.0})
        self.assertEqual(self.template.minimum_price, 70.0)
        self.assertTrue(self.template.minimum_price_initialized)

        with self.assertRaises(AccessError):
            self.template.with_user(self.order_price_manager).write({'minimum_price': 60.0})
        with self.assertRaises(AccessError):
            self.template.with_user(self.sales_price_manager).write({'minimum_price': 60.0})

    def test_minimum_cannot_open_a_gap_under_the_sales_price(self):
        with self.assertRaises(UserError):
            self.template.with_user(self.accountant).write({'minimum_price': 150.0})
        self.assertEqual(self.template.minimum_price, 80.0)

    def test_price_manager_can_lower_sales_price_down_to_the_floor(self):
        self.template.with_user(self.order_price_manager).write({'list_price': 90.0})
        self.assertEqual(self.template.list_price, 90.0)
        self.template.with_user(self.sales_price_manager).write({'list_price': 80.0})
        self.assertEqual(self.template.list_price, 80.0)
        with self.assertRaises(UserError):
            self.template.with_user(self.order_price_manager).write({'list_price': 79.0})

    def test_sales_admin_without_price_group_cannot_change_sales_price(self):
        with self.assertRaises(AccessError):
            self.template.with_user(self.sales_admin).write({'list_price': 120.0})
        with self.assertRaises(AccessError):
            self.template.with_user(self.sales_admin).write({'list_price': 70.0})
        self.template.with_user(self.sales_admin).write({'name': 'Renamed Floor Product'})
        self.assertEqual(self.template.name, 'Renamed Floor Product')

    def test_price_only_manager_cannot_edit_other_product_fields(self):
        with self.assertRaises(AccessError):
            self.template.with_user(self.order_price_manager).write({'name': 'Not allowed'})

    def test_zero_minimum_is_no_floor(self):
        self.template.with_user(self.accountant).write({'minimum_price': 0.0})
        self.template.with_user(self.order_price_manager).write({'list_price': 1.0})
        self.assertEqual(self.template.list_price, 1.0)
        order = self._order()
        line = self._line(order)
        line.write({'price_unit': 0.0, 'discount': 100.0})
        self.assertEqual(line.price_unit, 0.0)

    def test_sale_line_unit_price_and_discount_respect_the_floor(self):
        order = self._order()
        line = self._line(order)
        line.write({'price_unit': 80.0})
        self.assertEqual(line.price_unit, 80.0)
        with self.assertRaises(UserError):
            line.write({'price_unit': 79.0})
        line.write({'price_unit': 100.0, 'discount': 0.0})
        with self.assertRaises(UserError):
            line.write({'discount': 30.0})
        line.write({'discount': 20.0})
        self.assertEqual(line.discount, 20.0)

    def test_line_already_below_the_floor_can_be_saved_if_it_does_not_get_worse(self):
        self.template.with_user(self.accountant).write({'minimum_price': 0.0})
        order = self._order()
        line = self._line(order)
        line.write({'price_unit': 40.0})
        self.env.cr.execute(
            "UPDATE product_template SET minimum_price = 100 WHERE id = %s",
            [self.template.id],
        )
        self.template.invalidate_recordset(['minimum_price'])
        self.product.invalidate_recordset(['minimum_price'])
        line.write({'price_unit': 40.0})
        with self.assertRaises(UserError):
            line.write({'price_unit': 30.0})
        line.write({'price_unit': 100.0})

    def test_order_discount_line_cannot_pull_the_net_under_the_floor(self):
        order = self._order()
        line = self._line(order)
        line.write({'price_unit': 100.0, 'discount': 0.0})
        discount_product = self.env['product.product'].create({
            'name': 'Order Discount',
            'detailed_type': 'service',
            'list_price': 0.0,
        })
        order.company_id.sale_discount_product_id = discount_product
        with self.assertRaises(UserError):
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': discount_product.id,
                'product_uom_qty': 1.0,
                'price_unit': -30.0,
            })
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': discount_product.id,
            'product_uom_qty': 1.0,
            'price_unit': -20.0,
        })

    def test_fixed_and_percentage_pricelist_items_respect_the_floor(self):
        PricelistItem = self.env['product.pricelist.item']
        PricelistItem.create({
            'pricelist_id': self.pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': self.template.id,
            'compute_price': 'fixed',
            'fixed_price': 80.0,
        })
        with self.assertRaises(UserError):
            PricelistItem.create({
                'pricelist_id': self.pricelist.id,
                'applied_on': '0_product_variant',
                'product_id': self.product.id,
                'compute_price': 'fixed',
                'fixed_price': 50.0,
            })
        with self.assertRaises(UserError):
            PricelistItem.create({
                'pricelist_id': self.pricelist.id,
                'applied_on': '1_product',
                'product_tmpl_id': self.template.id,
                'compute_price': 'percentage',
                'percent_price': 30.0,
            })
        PricelistItem.create({
            'pricelist_id': self.pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': self.template.id,
            'compute_price': 'percentage',
            'percent_price': 10.0,
        })
        with self.assertRaises(UserError):
            PricelistItem.create({
                'pricelist_id': self.pricelist.id,
                'applied_on': '1_product',
                'product_tmpl_id': self.template.id,
                'compute_price': 'formula',
                'base': 'list_price',
                'price_discount': 30.0,
            })

    def test_global_pricelist_rule_is_not_blocked_but_the_sale_line_is(self):
        self.env['product.pricelist.item'].create({
            'pricelist_id': self.pricelist.id,
            'applied_on': '3_global',
            'compute_price': 'fixed',
            'fixed_price': 10.0,
        })
        order = self._order()
        with self.assertRaises(UserError):
            self._line(order)

    def test_populate_is_idempotent_and_keeps_an_explicit_zero(self):
        product = self.env['product.product'].create({
            'name': 'Migrate Me',
            'list_price': 55.0,
            'detailed_type': 'consu',
        })
        template = product.product_tmpl_id
        self.env.cr.execute(
            """
            UPDATE product_template
               SET minimum_price = 0,
                   minimum_price_initialized = FALSE
             WHERE id = %s
            """,
            [template.id],
        )
        template.invalidate_recordset(['minimum_price', 'minimum_price_initialized'])
        low_pricelist = self.env['product.pricelist'].create({'name': 'Already Low'})
        item = self.env['product.pricelist.item'].create({
            'pricelist_id': low_pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': template.id,
            'compute_price': 'fixed',
            'fixed_price': 40.0,
        })

        populate_minimum_prices(self.env)
        template.invalidate_recordset(['minimum_price', 'minimum_price_initialized'])
        self.assertEqual(template.minimum_price, 55.0)
        self.assertTrue(template.minimum_price_initialized)
        self.assertEqual(item.fixed_price, 40.0)

        template.with_user(self.accountant).write({'minimum_price': 0.0})
        populate_minimum_prices(self.env)
        template.invalidate_recordset(['minimum_price', 'minimum_price_initialized'])
        self.assertEqual(template.minimum_price, 0.0)
        self.assertTrue(template.minimum_price_initialized)

    def test_variant_floor_adds_the_extra_price(self):
        attribute = self.env['product.attribute'].create({'name': 'Size'})
        small = self.env['product.attribute.value'].create({
            'name': 'S', 'attribute_id': attribute.id,
        })
        large = self.env['product.attribute.value'].create({
            'name': 'L', 'attribute_id': attribute.id,
        })
        template = self.env['product.template'].create({
            'name': 'Sized Product',
            'list_price': 100.0,
            'detailed_type': 'consu',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, [small.id, large.id])],
            })],
        })
        template.minimum_price = 80.0
        large_value = template.attribute_line_ids.product_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id == large
        )
        large_value.price_extra = 15.0
        variant_small = template.product_variant_ids.filtered(
            lambda product: small in product.product_template_attribute_value_ids.product_attribute_value_id
        )
        variant_large = template.product_variant_ids.filtered(
            lambda product: large in product.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.assertEqual(variant_small.minimum_price, 80.0)
        self.assertEqual(variant_large.minimum_price, 95.0)

    def test_floor_is_converted_into_the_line_uom(self):
        dozen = self.env.ref('uom.product_uom_dozen')
        order = self._order()
        line = self._line(order)
        line.write({'product_uom': dozen.id, 'price_unit': 1200.0})
        with self.assertRaises(UserError):
            line.write({'price_unit': 900.0})
