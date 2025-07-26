/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { WebsitePreview } from "@website/client_actions/website_preview/website_preview";

patch(WebsitePreview.prototype, {
    setup() {
        const _super = super.setup(...arguments);
        
        // Interceptar después de que se ejecute onWillStart
        const originalOnWillStart = this.onWillStart;
        this.onWillStart = async function() {
            await originalOnWillStart.call(this);
            
            // Corregir la URL inicial si existe y es relativa
            if (this.initialUrl && this.initialUrl.startsWith('/')) {
                // Usar HTTPS explícitamente
                const protocol = 'https:';
                const host = window.location.host;
                this.initialUrl = `${protocol}//${host}${this.initialUrl}`;
                
                console.log('Website Preview HTTPS Fix: URL corregida a', this.initialUrl);
            }
        };
        
        return _super;
    }
});
