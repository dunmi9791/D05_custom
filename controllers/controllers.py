# -*- coding: utf-8 -*-
# from odoo import http


# class D05Customs(http.Controller):
#     @http.route('/d05_customs/d05_customs', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/d05_customs/d05_customs/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('d05_customs.listing', {
#             'root': '/d05_customs/d05_customs',
#             'objects': http.request.env['d05_customs.d05_customs'].search([]),
#         })

#     @http.route('/d05_customs/d05_customs/objects/<model("d05_customs.d05_customs"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('d05_customs.object', {
#             'object': obj
#         })

