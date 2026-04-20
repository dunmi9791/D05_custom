from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, ValidationError
import json
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import io
import base64


class PartnerStatementAPI(http.Controller):

    ### 1. Partner Data Endpoint
    @http.route('/api/partners', type='json', auth='user', methods=['GET'], csrf=False)
    def get_partners(self, search_term=None, limit=100, offset=0, **kw):
        """
        Retrieve a list of business partners (only credit customers).
        """
        try:
            domain = [('customer_rank', '>', 0), ('customer_type', '=', 'credit')]  # Only credit customers
            if search_term:
                domain += ['|', ('name', 'ilike', search_term), ('customer_type', 'ilike', search_term)]

            partners = request.env['res.partner'].search(
                domain, limit=int(limit), offset=int(offset)
            )
            result = [
                {
                    'id': partner.id,
                    'name': partner.name,
                    'address': partner.contact_address or '',
                    'type': 'Customer'
                } for partner in partners
            ]

            return {
                'status': 'success',
                'data': result,
                'total': request.env['res.partner'].search_count(domain)
            }

        except Exception as e:
            return {
                'status': 'error',
                'message': f"Error retrieving partners: {str(e)}"
            }, 500

    ### 2. Financial Summary Endpoint
    @http.route('/api/partners/<int:partner_id>/summary', type='json', auth='user', methods=['GET'], csrf=False)
    def get_partner_summary(self, partner_id, **kw):
        """
        Retrieve financial summary data for a specific partner.
        """
        try:
            partner = request.env['res.partner'].browse(partner_id)
            if not partner.exists():
                return {'status': 'error', 'message': 'Partner not found'}, 404

            today = date.today()
            domain = [
                ('partner_id', '=', partner_id),
                ('move_id.state', '=', 'posted'),
                ('full_reconcile_id', '=', False),
                ('account_id.reconcile', '=', True),
                ('account_id.non_trade', '=', False),
            ]

            # Fetch account move lines for receivables and payables
            move_lines = request.env['account.move.line'].search(domain)
            total_receivables = sum(
                line.balance for line in move_lines if line.account_id.account_type == 'asset_receivable')
            total_payables = sum(
                line.balance for line in move_lines if line.account_id.account_type == 'liability_payable')

            # Overdue amounts
            overdue_domain = domain + [('date_maturity', '<', today)]
            overdue_lines = request.env['account.move.line'].search(overdue_domain)
            overdue_receivables = sum(
                line.balance for line in overdue_lines if line.account_id.account_type == 'asset_receivable')
            overdue_payables = sum(
                line.balance for line in overdue_lines if line.account_id.account_type == 'liability_payable')

            return {
                'status': 'success',
                'data': {
                    'totalReceivables': round(total_receivables, 2),
                    'totalPayables': round(total_payables, 2),
                    'netBalance': round(total_receivables - total_payables, 2),
                    'overdueReceivables': round(overdue_receivables, 2),
                    'overduePayables': round(overdue_payables, 2)
                }
            }

        except Exception as e:
            return {
                'status': 'error',
                'message': f"Error retrieving financial summary: {str(e)}"
            }, 500

    ### 3. Transactions Endpoint
    @http.route('/api/partners/<int:partner_id>/transactions', type='json', auth='user', methods=['GET'], csrf=False)
    def get_partner_transactions(self, partner_id, dateRange=None, transactionType='all', status='all', sortBy='date',
                                 sortDirection='desc', limit=100, offset=0, **kw):
        """
        Retrieve transaction data for a specific partner.
        """
        try:
            partner = request.env['res.partner'].browse(partner_id)
            if not partner.exists():
                return {'status': 'error', 'message': 'Partner not found'}, 404

            today = date.today()
            domain = [
                ('partner_id', '=', partner_id),
                ('move_id.state', '=', 'posted'),
                ('account_id.reconcile', '=', True),
                ('account_id.non_trade', '=', False),
            ]

            # Apply date range filter
            if dateRange:
                if dateRange == 'last30':
                    domain += [('date', '>=', today - relativedelta(days=30))]
                elif dateRange == 'last90':
                    domain += [('date', '>=', today - relativedelta(days=90))]
                elif dateRange == 'year':
                    domain += [('date', '>=', today - relativedelta(years=1))]

            # Apply transaction type filter
            if transactionType != 'all':
                account_type = 'asset_receivable' if transactionType == 'receivable' else 'liability_payable'
                domain += [('account_id.account_type', '=', account_type)]

            # Apply status filter
            if status != 'all':
                if status == 'open':
                    domain += [('full_reconcile_id', '=', False), ('date_maturity', '>=', today)]
                elif status == 'overdue':
                    domain += [('full_reconcile_id', '=', False), ('date_maturity', '<', today)]
                elif status == 'paid':
                    domain += [('full_reconcile_id', '!=', False)]

            # Sorting
            sort_field = 'date' if sortBy not in ['date', 'amount', 'dueDate'] else sortBy
            sort_field = 'date_maturity' if sortBy == 'dueDate' else sort_field
            order = f"{sort_field} {sortDirection}"

            # Fetch move lines
            move_lines = request.env['account.move.line'].search(
                domain, limit=int(limit), offset=int(offset), order=order
            )
            total = request.env['account.move.line'].search_count(domain)

            transactions = [
                {
                    'id': line.id,
                    'type': 'Receivable' if line.account_id.account_type == 'asset_receivable' else 'Payable',
                    'docNumber': line.move_id.name or '',
                    'date': line.date.strftime('%Y-%m-%d'),
                    'dueDate': line.date_maturity.strftime('%Y-%m-%d') if line.date_maturity else '',
                    'amount': round(line.balance, 2),
                    'status': (
                        'Paid' if line.full_reconcile_id else
                        'Overdue' if line.date_maturity and line.date_maturity < today else
                        'Open'
                    )
                } for line in move_lines
            ]

            return {
                'status': 'success',
                'data': {
                    'total': total,
                    'transactions': transactions
                }
            }

        except Exception as e:
            return {
                'status': 'error',
                'message': f"Error retrieving transactions: {str(e)}"
            }, 500

    ### 4. PDF Export Endpoint
    @http.route('/api/partners/<int:partner_id>/export/pdf', type='http', auth='user', methods=['GET'], csrf=False)
    def export_partner_statement_pdf(self, partner_id, dateRange=None, includeDetails=False, **kw):
        """
        Generate and return a PDF statement for a specific partner.
        """
        try:
            partner = request.env['res.partner'].browse(partner_id)
            if not partner.exists():
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Partner not found'}),
                    headers={'Content-Type': 'application/json'},
                    status=404
                )

            # Prepare data for the report
            today = date.today()
            domain = [
                ('partner_id', '=', partner_id),
                ('move_id.state', '=', 'posted'),
                ('account_id.reconcile', '=', True),
                ('account_id.non_trade', '=', False),
            ]

            if dateRange:
                if dateRange == 'last30':
                    domain += [('date', '>=', today - relativedelta(days=30))]
                elif dateRange == 'last90':
                    domain += [('date', '>=', today - relativedelta(days=90))]
                elif dateRange == 'year':
                    domain += [('date', '>=', today - relativedelta(years=1))]

            move_lines = request.env['account.move.line'].search(domain)
            data = {
                'partner_id': partner_id,
                'date_range': dateRange or 'all',
                'include_details': includeDetails,
                'move_line_ids': move_lines.ids
            }

            # Generate PDF using an existing or custom report
            report_action = request.env.ref('account.action_report_account_statement').report_action(
                [], data=data
            )
            pdf_content, _ = request.env['ir.actions.report']._render_qweb_pdf(
                'account.action_report_account_statement', [partner_id], data=data
            )

            headers = {
                'Content-Type': 'application/pdf',
                'Content-Disposition': f'attachment; filename="partner_statement_{partner_id}.pdf"',
                'Content-Length': len(pdf_content)
            }
            return request.make_response(pdf_content, headers=headers)

        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': f"Error generating PDF: {str(e)}"}),
                headers={'Content-Type': 'application/json'},
                status=500
            )