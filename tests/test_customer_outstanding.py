# -*- coding: utf-8 -*-
from types import SimpleNamespace

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCustomerOutstanding(TransactionCase):
    """Partner-ledger outstanding balances.

    Not run in the agent environment (no Odoo runtime). Run on a staging
    database with ``--test-tags /D05_custom:TestCustomerOutstanding``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.as_of = fields.Date.to_date('2026-11-20')
        cls.later = fields.Date.to_date('2026-11-25')
        cls.north = cls._setup_branch('Outstanding North', 'N')
        cls.south = cls._setup_branch('Outstanding South', 'S')

        cls.cash_partner = cls._partner('Cash Open', 'cash')
        cls.credit_partner = cls._partner('Credit Open', 'credit')
        cls.settled_partner = cls._partner('Settled Unreconciled', 'cash')
        cls.both_partner = cls._partner('Two Branches', 'credit')
        cls.parent_partner = cls._partner('Household Parent', 'cash')
        cls.child_partner = cls.env['res.partner'].create({
            'name': 'Household Contact',
            'parent_id': cls.parent_partner.id,
            'type': 'contact',
        })
        cls.future_partner = cls._partner('Future Only', 'cash')
        cls.unapplied_partner = cls._partner('Unapplied Payment', 'cash')
        cls.payable_partner = cls._partner('Payable Only', 'cash')
        cls.draft_partner = cls._partner('Draft Only', 'cash')

        for partner in (
            cls.cash_partner, cls.credit_partner, cls.settled_partner,
            cls.both_partner, cls.parent_partner, cls.future_partner,
            cls.unapplied_partner, cls.draft_partner,
        ):
            cls._assign_receivable(partner, cls.north)
        cls._assign_receivable(cls.both_partner, cls.south)

        cls.cash_invoice = cls._invoice(cls.cash_partner, cls.north, 1000.0, '2026-11-01')
        cls.cash_payment = cls._payment(cls.cash_partner, cls.north, 400.0, '2026-11-02')
        cls._invoice(cls.credit_partner, cls.north, 250.0, '2026-11-01')
        cls.settled_invoice = cls._invoice(cls.settled_partner, cls.north, 500.0, '2026-11-01')
        cls._payment(cls.settled_partner, cls.north, 500.0, '2026-11-02')
        cls._invoice(cls.both_partner, cls.north, 100.0, '2026-11-01')
        cls._invoice(cls.both_partner, cls.south, 80.0, '2026-11-01')
        # Invoicing the contact posts the receivable on the commercial partner.
        cls._invoice(cls.child_partner, cls.north, 70.0, '2026-11-01')
        cls._invoice(cls.future_partner, cls.north, 40.0, '2026-11-25')
        cls._payment(cls.unapplied_partner, cls.north, 150.0, '2026-11-02')
        cls._invoice(cls.draft_partner, cls.north, 999.0, '2026-11-01', post=False)
        cls._payable_entry(cls.payable_partner, cls.north, 300.0, '2026-11-01')

    @classmethod
    def _setup_branch(cls, name, suffix):
        company = cls.env['res.company'].create({
            'name': name,
            'currency_id': cls.env.company.currency_id.id,
        })
        receivable = cls._account(company, 'Receivable %s' % suffix, 'TAR%s' % suffix, 'asset_receivable', True)
        income = cls._account(company, 'Income %s' % suffix, 'TIN%s' % suffix, 'income', False)
        outstanding = cls._account(company, 'Outstanding %s' % suffix, 'TOU%s' % suffix, 'asset_current', False)
        liquidity = cls._account(company, 'Bank %s' % suffix, 'TCS%s' % suffix, 'asset_cash', False)
        payable = cls._account(company, 'Payable %s' % suffix, 'TPA%s' % suffix, 'liability_payable', True)
        expense = cls._account(company, 'Expense %s' % suffix, 'TEX%s' % suffix, 'expense', False)
        company.write({
            'account_journal_payment_debit_account_id': outstanding.id,
            'account_journal_payment_credit_account_id': outstanding.id,
        })
        sale = cls.env['account.journal'].with_company(company).create({
            'name': 'Sales %s' % suffix,
            'code': 'TS%s' % suffix,
            'type': 'sale',
            'company_id': company.id,
            'default_account_id': income.id,
        })
        bank = cls.env['account.journal'].with_company(company).create({
            'name': 'Bank %s' % suffix,
            'code': 'TB%s' % suffix,
            'type': 'bank',
            'company_id': company.id,
            'default_account_id': liquidity.id,
        })
        for method in bank.inbound_payment_method_line_ids:
            if not method.payment_account_id:
                method.payment_account_id = outstanding
        misc = cls.env['account.journal'].with_company(company).create({
            'name': 'Misc %s' % suffix,
            'code': 'TG%s' % suffix,
            'type': 'general',
            'company_id': company.id,
        })
        return SimpleNamespace(
            company=company,
            receivable=receivable,
            income=income,
            payable=payable,
            expense=expense,
            sale_journal=sale,
            bank_journal=bank,
            misc_journal=misc,
        )

    @classmethod
    def _account(cls, company, name, code, account_type, reconcile):
        return cls.env['account.account'].create({
            'name': name,
            'code': code,
            'account_type': account_type,
            'reconcile': reconcile,
            'company_id': company.id,
        })

    @classmethod
    def _partner(cls, name, customer_type):
        partner = cls.env['res.partner'].create({
            'name': name,
            'company_type': 'company',
            'is_company': True,
        })
        if customer_type != 'cash':
            partner.customer_type = customer_type
        return partner

    @classmethod
    def _assign_receivable(cls, partner, branch):
        partner.with_company(branch.company).property_account_receivable_id = branch.receivable

    @classmethod
    def _invoice(cls, partner, branch, amount, invoice_date, post=True):
        move = cls.env['account.move'].with_company(branch.company).create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': invoice_date,
            'date': invoice_date,
            'company_id': branch.company.id,
            'journal_id': branch.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Goods',
                'quantity': 1.0,
                'price_unit': amount,
                'account_id': branch.income.id,
                'tax_ids': [(6, 0, [])],
            })],
        })
        if post:
            move.action_post()
            if branch.company.currency_id.compare_amounts(move.amount_total, amount):
                raise AssertionError(
                    'Invoice total %s != %s (unexpected tax or currency).' % (move.amount_total, amount)
                )
        return move

    @classmethod
    def _payment(cls, partner, branch, amount, payment_date):
        payment = cls.env['account.payment'].with_company(branch.company).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner.id,
            'amount': amount,
            'date': payment_date,
            'journal_id': branch.bank_journal.id,
        })
        payment.action_post()
        receivable_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable'
        )
        credited = -sum(receivable_lines.mapped('balance'))
        if branch.company.currency_id.compare_amounts(credited, amount):
            raise AssertionError(
                'Payment credited receivable %s, expected %s.' % (credited, amount)
            )
        if payment.is_reconciled:
            raise AssertionError('Payment was reconciled; the test needs it open.')
        return payment

    @classmethod
    def _payable_entry(cls, partner, branch, amount, entry_date):
        move = cls.env['account.move'].with_company(branch.company).create({
            'move_type': 'entry',
            'partner_id': partner.id,
            'date': entry_date,
            'company_id': branch.company.id,
            'journal_id': branch.misc_journal.id,
            'line_ids': [
                (0, 0, {
                    'name': 'Payable',
                    'account_id': branch.payable.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
                (0, 0, {
                    'name': 'Expense',
                    'account_id': branch.expense.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
            ],
        })
        move.action_post()
        return move

    def _rows(self, as_of=None, companies=None):
        as_of = as_of or self.as_of
        if companies is None:
            companies = self.north.company | self.south.company
        rows = self.env['d05.customer.outstanding']._prepare_rows(as_of, companies)
        return {(row['partner_id'], row['company_id']): row['balance'] for row in rows}

    def _assert_amount(self, company, actual, expected):
        self.assertEqual(
            company.currency_id.compare_amounts(actual, expected),
            0,
            '%s != %s' % (actual, expected),
        )

    def test_non_zero_filter(self):
        rows = self._rows()
        self.assertNotIn((self.settled_partner.id, self.north.company.id), rows)
        # The invoice is still unpaid because the matching payment was not reconciled.
        self._assert_amount(self.north.company, self.settled_invoice.amount_residual, 500.0)
        self._assert_amount(self.north.company, self.settled_partner.outstanding_total, 500.0)
        self.assertNotIn((self.draft_partner.id, self.north.company.id), rows)
        self.assertNotIn((self.future_partner.id, self.north.company.id), rows)
        self.assertNotIn((self.payable_partner.id, self.north.company.id), rows)
        # A posted payment with no invoice is a credit balance and is kept.
        self.assertFalse(self.unapplied_partner.customer_rank)
        self._assert_amount(
            self.north.company,
            rows[(self.unapplied_partner.id, self.north.company.id)],
            -150.0,
        )
        self._assert_amount(
            self.north.company,
            rows[(self.cash_partner.id, self.north.company.id)],
            600.0,
        )

    def test_cash_and_credit_customers_both_appear(self):
        rows = self._rows()
        self.assertEqual(self.cash_partner.customer_type, 'cash')
        self.assertEqual(self.credit_partner.customer_type, 'credit')
        self._assert_amount(
            self.north.company,
            rows[(self.cash_partner.id, self.north.company.id)],
            600.0,
        )
        self._assert_amount(
            self.north.company,
            rows[(self.credit_partner.id, self.north.company.id)],
            250.0,
        )

    def test_split_by_company(self):
        rows = self._rows()
        self._assert_amount(
            self.north.company,
            rows[(self.both_partner.id, self.north.company.id)],
            100.0,
        )
        self._assert_amount(
            self.south.company,
            rows[(self.both_partner.id, self.south.company.id)],
            80.0,
        )
        partner_rows = [key for key in rows if key[0] == self.both_partner.id]
        self.assertEqual(len(partner_rows), 2)

    def test_unreconciled_payment_included_unlike_invoice_residual(self):
        """Ledger balance includes the open payment; the invoice residual does not."""
        self.assertEqual(self.cash_invoice.payment_state, 'not_paid')
        self.assertFalse(self.cash_payment.is_reconciled)
        self._assert_amount(self.north.company, self.cash_invoice.amount_residual_signed, 1000.0)
        self._assert_amount(self.north.company, self.cash_partner.outstanding_total, 1000.0)
        rows = self._rows(companies=self.north.company)
        self._assert_amount(
            self.north.company,
            rows[(self.cash_partner.id, self.north.company.id)],
            600.0,
        )

    def test_commercial_partner_rolls_up_contacts(self):
        rows = self._rows(companies=self.north.company)
        self.assertNotIn(self.child_partner.id, {partner_id for partner_id, _company in rows})
        self._assert_amount(
            self.north.company,
            rows[(self.parent_partner.id, self.north.company.id)],
            70.0,
        )

    def test_as_of_date(self):
        hidden = self._rows(as_of=self.as_of, companies=self.north.company)
        self.assertNotIn((self.future_partner.id, self.north.company.id), hidden)
        shown = self._rows(as_of=self.later, companies=self.north.company)
        self._assert_amount(
            self.north.company,
            shown[(self.future_partner.id, self.north.company.id)],
            40.0,
        )

    def test_access_rights(self):
        group = self.env.ref('D05_custom.group_customer_outstanding')
        self.assertFalse(group.implied_ids)
        menu = self.env.ref('D05_custom.menu_customer_outstanding')
        self.assertEqual(menu.groups_id, group)
        self.assertEqual(menu.parent_id, self.env.ref('account.menu_finance_reports'))
        action = self.env.ref('D05_custom.action_customer_outstanding_wizard')
        self.assertIn(group, action.groups_id)

        reader = self._make_user('outstanding_reader', [group.id])
        outsider = self._make_user('outstanding_outsider', [])

        Menu = self.env['ir.ui.menu']
        self.assertNotIn(menu.id, Menu.with_user(outsider)._visible_menu_ids())
        self.assertIn(menu.id, Menu.with_user(reader)._visible_menu_ids())

        with self.assertRaises(AccessError):
            self.env['d05.customer.outstanding'].with_user(outsider).check_access_rights('read')
        with self.assertRaises(AccessError):
            self.env['d05.customer.outstanding.wizard'].with_user(outsider).search([])

        wizard = self.env['d05.customer.outstanding.wizard'].with_user(reader).create({
            'as_of_date': self.as_of,
            'company_ids': [(6, 0, (self.north.company | self.south.company).ids)],
        })
        action_result = wizard.action_view_balances()
        self.assertFalse(action_result['context'].get('search_default_filter_credit'))
        self.assertNotIn('customer_type', str(action_result['domain']))
        lines = self.env['d05.customer.outstanding'].with_user(reader).search(action_result['domain'])
        cash_line = lines.filtered(
            lambda line: line.partner_id.id == self.cash_partner.id
            and line.company_id.id == self.north.company.id
        )
        self.assertEqual(len(cash_line), 1)
        self._assert_amount(self.north.company, cash_line.balance, 600.0)
        # The outsider cannot read the rows the reader just opened.
        with self.assertRaises(AccessError):
            cash_line.with_user(outsider).read(['balance'])

    def _make_user(self, login, extra_group_ids):
        groups = [
            self.env.ref('base.group_user').id,
            self.env.ref('account.group_account_readonly').id,
            *extra_group_ids,
        ]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@example.com' % login,
            'company_id': self.north.company.id,
            'company_ids': [(6, 0, (self.north.company | self.south.company).ids)],
            'groups_id': [(6, 0, groups)],
        })
