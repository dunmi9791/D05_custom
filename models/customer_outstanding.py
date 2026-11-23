# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Receivable accounts only, matching Partner Ledger when Partner's is
# "Receivable Accounts" (accounting_pdf_reports result_selection = customer).
RECEIVABLE_ACCOUNT_TYPE = 'asset_receivable'


class D05CustomerOutstanding(models.TransientModel):
    """One row per commercial partner and branch (company).

    The balance is the Partner Ledger receivable total, not
    ``res.partner.outstanding_total``.

    Partner Ledger (Odoo Mates ``accounting_pdf_reports``, wizard defaults)
    sums ``debit - credit`` on posted journal items of non-deprecated
    receivable accounts. "Reconciled Entries" is ticked by default, so fully
    reconciled items stay in the sum; they net to zero. A payment that was
    posted and never reconciled is a credit on the receivable account and
    therefore reduces the balance. ``outstanding_total`` sums
    ``amount_residual_signed`` on unpaid customer invoices and credit notes,
    so that same payment is missing and the figure is higher.

    This model does not call ``accounting_pdf_reports``. The formula below is
    the same one the report uses (posted receivable ``debit - credit``), so a
    later change inside that module does not break this list. Compare a row
    with Partner Ledger for that company: Receivable Accounts, All Posted
    Entries, Reconciled Entries ticked, no start date, end date equal to the
    as-of date, every journal selected.

    Journal items store the commercial partner (Odoo sets
    ``account.move.line.partner_id`` from ``commercial_partner_id``). Rows are
    still grouped by commercial partner so a contact-level line, if one
    exists, rolls up to the same customer the ledger shows.

    Each ``res.company`` is a branch. Balances are in that company's currency
    and are not added across branches. Partner Ledger on a parent company also
    folds in child companies; this list keeps every company on its own row.
    D05 branches are separate companies, so the row matches the ledger when
    that branch is the active company.
    """

    _name = 'd05.customer.outstanding'
    _description = 'Customer Outstanding Balance'
    _order = 'partner_id, company_id'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner', string='Customer', readonly=True, required=True,
    )
    customer_type = fields.Selection(
        related='partner_id.customer_type',
        string='Customer Type',
        readonly=True,
        store=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Branch', readonly=True, required=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
    )
    balance = fields.Monetary(
        string='Outstanding Balance',
        currency_field='currency_id',
        readonly=True,
        help="Posted receivable journal items (debit minus credit) up to the "
             "as-of date, in the branch currency. Includes payments that were "
             "posted and not reconciled. Same total as the Partner Ledger "
             "balance for this customer and branch.",
    )
    as_of_date = fields.Date(string='As of', readonly=True, required=True)

    @api.model
    def _companies_for_report(self, companies):
        """Branches the user asked for, limited to companies they may access."""
        companies = companies.exists() if companies else self.env['res.company']
        if not self.env.su:
            companies &= self.env.user.company_ids
        if not companies:
            raise UserError(_("Select a branch you are allowed to see."))
        return companies

    @api.model
    def _prepare_rows(self, as_of_date, companies):
        """Non-zero receivable balances for ``as_of_date`` and ``companies``.

        :return: list of create-vals dicts (partner, company, balance, as-of)
        """
        if not as_of_date:
            raise UserError(_("Set the as-of date."))
        companies = self._companies_for_report(companies)
        # The switcher may have fewer companies than the wizard. Keep the
        # selected branches on the env used for journal items, partners, and
        # company currency, otherwise a customer restricted to an unticked
        # branch raises AccessError when commercial_partner_id is read.
        report = self.with_context(allowed_company_ids=list(companies.ids))
        companies = report.env['res.company'].browse(companies.ids)
        domain = [
            ('parent_state', '=', 'posted'),
            ('date', '<=', as_of_date),
            ('company_id', 'in', companies.ids),
            ('partner_id', '!=', False),
            ('account_id.account_type', '=', RECEIVABLE_ACCOUNT_TYPE),
            ('account_id.deprecated', '=', False),
            ('display_type', 'not in', ('line_section', 'line_note')),
        ]
        grouped = report.env['account.move.line'].read_group(
            domain,
            ['balance:sum'],
            ['partner_id', 'company_id'],
            lazy=False,
        )
        partner_ids = [
            group['partner_id'][0] for group in grouped if group.get('partner_id')
        ]
        partners = report.env['res.partner'].browse(partner_ids)
        commercial_of = {
            partner.id: partner.commercial_partner_id.id for partner in partners
        }
        totals = defaultdict(float)
        for group in grouped:
            partner = group.get('partner_id')
            company = group.get('company_id')
            if not partner or not company:
                continue
            key = (commercial_of[partner[0]], company[0])
            totals[key] += group.get('balance') or 0.0

        company_by_id = {company.id: company for company in companies}
        rows = []
        for (partner_id, company_id), balance in totals.items():
            company = company_by_id.get(company_id)
            if not company:
                continue
            rounded = company.currency_id.round(balance)
            if company.currency_id.is_zero(rounded):
                continue
            rows.append({
                'partner_id': partner_id,
                'company_id': company_id,
                'balance': rounded,
                'as_of_date': as_of_date,
            })
        return rows


class D05CustomerOutstandingWizard(models.TransientModel):
    _name = 'd05.customer.outstanding.wizard'
    _description = 'Customer Outstanding Balances'

    as_of_date = fields.Date(
        string='As of',
        required=True,
        default=fields.Date.context_today,
        help="Journal items dated after this day are left out. Use the same "
             "day as Partner Ledger's End Date. The default is today.",
    )
    company_ids = fields.Many2many(
        'res.company',
        string='Branches',
        required=True,
        default=lambda self: self.env.user.company_ids,
        help="One row per customer per branch. Defaults to every company you "
             "can access, not only the company selected in the switcher.",
    )

    def action_view_balances(self):
        self.ensure_one()
        outstanding = self.env['d05.customer.outstanding']
        companies = outstanding._companies_for_report(self.company_ids)
        company_ids = list(companies.ids)
        # Same company context as the aggregation, so creating the rows
        # (customer type) and opening the list (partner name) can read a
        # customer whose company is selected here but unticked in the switcher.
        report = outstanding.with_context(allowed_company_ids=company_ids)
        # Keep a single run on screen if the user clears the id filter.
        report.search([('create_uid', '=', self.env.uid)]).unlink()
        lines = report.create(report._prepare_rows(self.as_of_date, companies))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Customer Outstanding Balances'),
            'res_model': 'd05.customer.outstanding',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', lines.ids)],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
                'allowed_company_ids': company_ids,
            },
            'target': 'current',
        }
