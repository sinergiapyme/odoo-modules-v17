{
    'name': 'Website Public Files',
    'version': '17.0.1.0.0',
    'category': 'Website',
    'summary': 'Public file manager using filestore',
    'depends': ['base', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'views/website_public_file_views.xml',
        'views/website_public_file_menu.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': False,
}
