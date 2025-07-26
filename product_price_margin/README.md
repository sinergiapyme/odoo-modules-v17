# Product Price Margin

Módulo para Odoo 17 Community Edition que permite gestionar márgenes de ganancia en productos y actualizar automáticamente los precios de venta.

## 📋 Descripción

Este módulo agrega funcionalidad de margen de ganancia a los productos, permitiendo calcular automáticamente el precio de venta basado en el costo estándar más un porcentaje de margen definido. Ideal para empresas que necesitan mantener sus precios actualizados según los cambios en los costos de compra.

## ✨ Características Principales

### 🔢 Gestión de Márgenes
- **Campo de porcentaje de margen**: Define el margen de ganancia deseado para cada producto
- **Cálculo automático**: El precio de venta se calcula como: `Precio Costo × (1 + Margen/100)`
- **Soporte para márgenes negativos**: Útil para promociones o liquidaciones (límite: -100%)

### 🔄 Actualización Automática
- **Actualización en tiempo real**: El precio se recalcula al cambiar el costo o margen
- **Control por producto**: Cada producto puede activar/desactivar la actualización automática
- **Registro de cambios**: Fecha y hora de la última actualización del costo

### ⏰ Automatización
- **Cron job configurable**: Actualización masiva programada (por defecto: diaria)
- **Actualización selectiva**: Solo actualiza productos con cambios significativos (> 0.01)
- **Logs detallados**: Registro completo de operaciones para auditoría

### 🛠️ Herramientas de Gestión
- **Actualización masiva manual**: Menú dedicado para actualizar todos los precios
- **Acción en lote**: Actualizar precios de productos seleccionados
- **Filtros avanzados**: Buscar productos con/sin margen, con actualización automática
- **Agrupación por margen**: Visualizar productos agrupados por porcentaje

## 📦 Instalación

### Requisitos Previos
- Odoo 17 Community Edition
- Módulos dependientes: `product`, `sale`
- Compatible con localización Argentina de ADHOC

### Pasos de Instalación

1. **Copiar el módulo al directorio de addons**:
   ```bash
   cp -r product_price_margin /ruta/a/odoo/addons/
   ```

2. **Establecer permisos correctos**:
   ```bash
   chmod -R 755 /ruta/a/odoo/addons/product_price_margin
   chown -R odoo:odoo /ruta/a/odoo/addons/product_price_margin
   ```

3. **Actualizar la lista de aplicaciones**:
   - Desde la interfaz: Aplicaciones → Actualizar lista de aplicaciones
   - Por línea de comandos: 
     ```bash
     ./odoo-bin -u base -d nombre_base_datos
     ```

4. **Instalar el módulo**:
   - Buscar "Product Price Margin" en Aplicaciones
   - Hacer clic en Instalar

## 🚀 Uso

### Configuración Inicial

1. **Definir margen en productos**:
   - Ir a Ventas → Productos → Productos
   - Editar un producto
   - En la pestaña "Información General", establecer el "Margen (%)"
   - El "Precio de Venta Calculado" se mostrará automáticamente

2. **Configurar actualización automática**:
   - En cada producto, marcar/desmarcar "Actualizar Precio Automáticamente"
   - Los productos marcados se actualizarán con el cron job

### Operaciones Diarias

#### Actualización Manual Individual
- En la vista de producto, hacer clic en el botón "Actualizar Precio" (🔄)
- Disponible cuando el precio calculado difiere del precio actual

#### Actualización Masiva
- Menú: Ventas → Productos → Actualizar Precios por Margen
- Actualiza todos los productos con margen definido
- Muestra notificación con resultados

#### Actualización por Lote
- Seleccionar productos en la vista lista
- Acción → Actualizar Precios según Margen

### Ejemplos de Cálculo

| Precio Costo | Margen | Precio Venta Calculado | Uso Típico |
|--------------|--------|------------------------|-------------|
| $1,000 | 0% | $1,000 | Venta al costo |
| $1,000 | 30% | $1,300 | Margen estándar |
| $1,000 | 50% | $1,500 | Margen alto |
| $1,000 | -20% | $800 | Promoción/Liquidación |

## ⚙️ Configuración Avanzada

### Modificar Frecuencia del Cron

1. Ir a: Configuración → Técnico → Automatización → Acciones planificadas
2. Buscar: "Actualizar Precios de Venta según Margen"
3. Opciones de configuración:
   - **Cada hora**: Intervalo = 1, Tipo = Horas
   - **Cada 6 horas**: Intervalo = 6, Tipo = Horas
   - **Dos veces al día**: Intervalo = 12, Tipo = Horas
   - **Semanalmente**: Intervalo = 1, Tipo = Semanas

### Permisos y Seguridad

- **Ver campos**: Todos los usuarios con acceso a productos
- **Botón actualizar**: Grupo `sales_team.group_sale_salesman`
- **Menú actualización masiva**: Grupo `sales_team.group_sale_manager`

## 🔍 Funciones Técnicas

### Campos Agregados a `product.template`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `margin_percent` | Float | Porcentaje de margen sobre el costo |
| `sale_price_computed` | Float (calculado) | Precio de venta calculado |
| `last_cost_update` | Datetime | Última actualización del costo |
| `auto_update_price` | Boolean | Activar actualización automática |

### Métodos Principales

- `_compute_sale_price()`: Calcula el precio según margen
- `action_update_sale_price()`: Actualiza precio de productos seleccionados
- `cron_update_prices_by_margin()`: Ejecutado por el cron job
- `action_update_all_prices_with_margin()`: Actualización masiva manual

## 📊 Casos de Uso

### Para Empresas con Inflación Alta
- Configurar cron para ejecutarse varias veces al día
- Mantener márgenes consistentes ante cambios de costos
- Registro histórico de actualizaciones para auditoría

### Para Retail/Distribución
- Definir márgenes por categoría de producto
- Actualizaciones automáticas al recibir nuevas compras
- Control fino sobre qué productos actualizar

### Para Promociones
- Usar márgenes negativos temporalmente
- Desactivar actualización automática en productos en promoción
- Restaurar márgenes normales post-promoción

## 🐛 Solución de Problemas

### El precio no se actualiza automáticamente
1. Verificar que "Actualizar Precio Automáticamente" esté activo
2. Comprobar que el cron job esté activo
3. Revisar logs en: Configuración → Técnico → Logging → Logs

### Error al actualizar precios masivamente
- Verificar permisos del usuario
- Comprobar que no haya restricciones en listas de precios
- Revisar logs para errores específicos

## 📝 Notas Importantes

- El módulo respeta las configuraciones de decimales de Odoo
- Compatible con multi-moneda y multi-compañía
- No interfiere con listas de precios existentes
- Los cambios de precio se registran en el historial estándar de Odoo

## 🤝 Soporte

Desarrollado por: **Sinergia Pyme**  
Sitio web: [www.sinergiapyme.com](https://www.sinergiapyme.com)  
Licencia: LGPL-3

Para soporte o consultas sobre el módulo, contactar a través del sitio web.
