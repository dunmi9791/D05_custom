# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install')
class TestPricelistLines(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'Listed Product',
            'default_code': 'D05-REF-33',
            'list_price': 100.0,
            'detailed_type': 'consu',
        })
        cls.template = cls.product.product_tmpl_id
        cls.template.minimum_price = 80.0
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': 'Branch Default',
            'company_id': cls.env.company.id,
        })
        cls.item = cls.env['product.pricelist.item'].create({
            'pricelist_id': cls.pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': cls.template.id,
            'compute_price': 'fixed',
            'fixed_price': 90.0,
        })
        cls.order_price_manager = cls._make_user(
            'd05_line_so_mgr', 'D05_custom.group_sales_order_price_manager',
        )
        cls.accountant = cls._make_user('d05_line_accountant', 'account.group_account_manager')
        cls.sales_admin = cls._make_user('d05_line_sales_admin', 'sales_team.group_sale_manager')
        cls.salesman = cls._make_user('d05_line_salesman', 'sales_team.group_sale_salesman')

    @classmethod
    def _make_user(cls, login, group_xmlid):
        groups = cls.env.ref('base.group_user') | cls.env.ref(group_xmlid)
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@d05.test' % login,
            'company_id': cls.env.company.id,
            'company_ids': [(6, 0, [cls.env.company.id])],
            'groups_id': [(6, 0, groups.ids)],
        })

    def test_search_by_internal_reference(self):
        found = self.env['product.pricelist.item'].search([
            ('default_code', '=', 'D05-REF-33'),
        ])
        self.assertIn(self.item, found)
        self.assertEqual(self.item.default_code, 'D05-REF-33')

    def test_price_manager_and_accountant_can_edit_down_to_the_floor(self):
        self.item.with_user(self.order_price_manager).write({'fixed_price': 80.0})
        self.assertEqual(self.item.fixed_price, 80.0)
        self.item.with_user(self.accountant).write({'fixed_price': 95.0})
        self.assertEqual(self.item.fixed_price, 95.0)
        with self.assertRaises(UserError):
            self.item.with_user(self.order_price_manager).write({'fixed_price': 10.0})
        self.assertEqual(self.item.fixed_price, 95.0)

    def test_sales_admin_and_salesman_cannot_edit_lines(self):
        Items = self.env['product.pricelist.item']
        self.assertTrue(Items.with_user(self.salesman).search([('id', '=', self.item.id)]))
        with self.assertRaises(AccessError):
            self.item.with_user(self.salesman).write({'fixed_price': 100.0})
        with self.assertRaises(AccessError):
            self.item.with_user(self.sales_admin).write({'fixed_price': 100.0})
        with self.assertRaises(AccessError):
            self.item.with_user(self.salesman).unlink()

    def test_lines_of_another_company_stay_hidden(self):
        other_company = self.env['res.company'].create({
            'name': 'Other Branch',
            'currency_id': self.env.company.currency_id.id,
        })
        other_pricelist = self.env['product.pricelist'].with_company(other_company).create({
            'name': 'Other Branch Prices',
            'company_id': other_company.id,
            'currency_id': other_company.currency_id.id,
        })
        other_item = self.env['product.pricelist.item'].with_company(other_company).create({
            'pricelist_id': other_pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': self.template.id,
            'compute_price': 'fixed',
            'fixed_price': 100.0,
        })
        visible = self.env['product.pricelist.item'].with_user(self.salesman).search([
            ('id', '=', other_item.id),
        ])
        self.assertFalse(visible)
        own = self.env['product.pricelist.item'].with_user(self.salesman).search([
            ('id', '=', self.item.id),
        ])
        self.assertTrue(own)

    def test_smart_button_opens_lines_for_that_pricelist(self):
        action = self.pricelist.action_open_pricelist_lines()
        self.assertEqual(action['res_model'], 'product.pricelist.item')
        self.assertEqual(action['domain'], [('pricelist_id', '=', self.pricelist.id)])
        self.assertEqual(self.pricelist.pricelist_line_count, 1)
        menu = self.env.ref('D05_custom.menu_pricelist_lines')
        self.assertEqual(menu.parent_id, self.env.ref('sale.product_menu_catalog'))
        view = self.env.ref('D05_custom.view_d05_pricelist_item_tree')
        self.assertIn('editable="bottom"', str(view.arch))
