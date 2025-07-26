{
    'name': 'Website Preview HTTPS Fix',
    'version': '17.0.1.0.0',
    'category': 'Website',
    'summary': 'Fix Mixed Content error in Website Preview',
    'description': """
        This module fixes the Mixed Content error when using Website Preview
        by ensuring the iframe URL uses HTTPS protocol.
    """,
    'depends': ['website'],
    'assets': {
        'web.assets_backend': [
            'website_preview_https_fix/static/src/js/website_preview_fix.js',
        ],
    },
    'auto_install': False,
    'installable': True,
    'application': False,
}
