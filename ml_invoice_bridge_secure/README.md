# MercadoLibre Invoice Bridge - Secure

Módulo seguro para subir facturas de Odoo a MercadoLibre, completamente reescrito para evitar corrupción del filestore.

## 🔥 Versión Segura

Esta es una **versión completamente reescrita** del módulo original que eliminó todos los patrones peligrosos que causaban corrupción del filestore en Odoo v17 CE.

### ✅ Problemas Solucionados

- **Método API Correcto**: Usa `_render_qweb_pdf()` en lugar del inexistente `render_qweb_pdf()`
- **Archivos Temporales**: Eliminado acceso directo al filestore usando context managers seguros
- **Manejo de Memoria**: Límites de 10MB por PDF y cleanup automático
- **Validaciones Robustas**: Permisos, formato de datos y validaciones de seguridad
- **Transacciones Seguras**: Commits individuales que evitan rollbacks masivos

## 📁 Estructura del Módulo

```
ml_invoice_bridge_secure/
├── __manifest__.py
├── __init__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── account_move.py          # Lógica principal SEGURA
│   ├── mercadolibre_config.py   # Configuración simplificada
│   └── mercadolibre_log.py      # Logging de operaciones
├── views/
│   ├── menu_views.xml
│   ├── account_move_views.xml
│   ├── mercadolibre_config_views.xml
│   └── mercadolibre_log_views.xml
├── security/
│   └── ir.model.access.csv
└── data/
    └── cron_data.xml
```

## 🚀 Instalación Rápida

### 1. Pre-requisitos

- Odoo v17 Community Edition
- Localización Argentina de ADHOC
- Odumbo configurado y sincronizando ventas
- Access Token de MercadoLibre

### 2. Instalación

```bash
# Copiar módulo a addons
cp -r ml_invoice_bridge_secure /opt/odoo/addons/

# Cambiar permisos
chown -R odoo:odoo /opt/odoo/addons/ml_invoice_bridge_secure

# Reiniciar Odoo
sudo systemctl restart odoo
```

### 3. Configuración

1. **Apps > Update Apps List**
2. **Apps > Search "MercadoLibre Invoice Bridge - Secure" > Install**
3. **MercadoLibre > Configuration > Create**
   - Name: "Producción ML"
   - Access Token: [Tu token de MercadoLibre]
   - Active: ✓
4. **Test Connection**

## 📋 Uso

### Subida Manual

1. Ir a **MercadoLibre > ML Invoices**
2. Seleccionar factura pendiente
3. Click **Upload to MercadoLibre**

### Subida Automática

1. **MercadoLibre > Configuration**
2. Activar **Auto Upload**: ✓
3. **Settings > Technical > Automation > Scheduled Actions**
4. Activar "MercadoLibre: Auto Upload Invoices"

## 🔍 Monitoreo

- **Logs**: MercadoLibre > Upload Logs
- **Facturas Pendientes**: MercadoLibre > ML Invoices (filtro automático)
- **Estado**: Verificar campo "Uploaded to ML" en facturas

## ⚠️ Diferencias con Módulo Original

| Aspecto | Módulo Original | Módulo Seguro |
|---------|----------------|---------------|
| **API Method** | `render_qweb_pdf()` ❌ | `_render_qweb_pdf()` ✅ |
| **File Handling** | Direct filestore access | Temporary files |
| **Memory** | No limits, leaks | 10MB limit, cleanup |
| **Error Handling** | Basic try/catch | Comprehensive validation |
| **Security** | None | Permission checks |
| **Performance** | Resource intensive | Optimized for high volume |

## 🛠️ Configuración para Alto Volumen

Para entornos con 100+ ventas diarias:

```ini
# /etc/odoo/odoo.conf
[options]
workers = 4
max_cron_threads = 2
limit_memory_soft = 671088640
limit_memory_hard = 805306368
```

## 🔧 Troubleshooting

### Factura no se sube

1. Verificar que `ml_pack_id` esté poblado
2. Verificar configuración activa
3. Test Connection en configuración
4. Revisar logs de error

### Múltiples errores

1. Verificar token válido
2. Revisar rate limits de MercadoLibre
3. Comprobar conectividad de red

## 📞 Soporte

- **Logs**: Siempre incluir logs de MercadoLibre > Upload Logs
- **Environment**: Versión Odoo, configuración, volumen de ventas
- **Steps**: Pasos para reproducir el problema

## 🔒 Seguridad

Este módulo ha sido diseñado con seguridad como prioridad:

- ✅ No acceso directo al filestore
- ✅ Validaciones de permisos
- ✅ Límites de recursos
- ✅ Manejo robusto de errores
- ✅ Logging detallado para auditoría

**Nunca más corrupción del filestore.**
