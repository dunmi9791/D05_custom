# -*- coding: utf-8 -*-
{
    'name': "d05_customs",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "My Company",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'sale'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'records/groups.xml',
        'views/templates.xml',
        'reports/sale_order_report.xml',
        'reports/paper.xml',
        'views/report_actions.xml',
        'views/sale_order_form_view.xml',

    ],
    'assets': {
            'web.assets_backend': [
                'D05_custom/static/src/css/report_style.css',
            ],
            'web.report_assets_common': [
                'D05_custom/static/src/css/report_style.css',
            ],
        },
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}

