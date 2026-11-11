# Actualización visual de la tienda

Se modificaron únicamente `templates/base.html`, `templates/index.html`, `static/css/style.css` y `static/js/main.js`. Se agregaron dos imágenes en `static/img/`.

- Encabezado sólido azul marino con detalles dorados, menor altura, buen contraste y enlaces activos indicados mediante `aria-current`.
- Logotipo original conservado sin alterar el archivo, el diseño ni sus colores.
- Banner con fotografía ilustrativa, overlay oscuro, `background-size: cover` y posiciones adaptadas al ancho de pantalla.
- Imágenes locales WebP: escritorio 1672 × 941 (179704 bytes), móvil 900 × 507 (71284 bytes). Precarga selectiva según pantalla. El fondo se utiliza exclusivamente en el inicio.
- Se retiró el rótulo superior «WILSON SAMUDIO REPRESENTACIONES». La frase exacta «Wilson Representaciones» no existía en las plantillas. Se conservaron las referencias comerciales del pie, contacto y títulos.
- Colores, bordes, botones y tarjetas armonizados; tipografía Manrope local conservada.
- Menú móvil con estado accesible, cierre al seleccionar un enlace, tocar fuera o pulsar Escape y reinicio al cambiar a escritorio.

## Verificación

Ejecutada con Flask test client, protección CSRF activa y SQLite exclusivamente en memoria. No se conectó a PostgreSQL ni se cambiaron datos reales.

- Compilación correcta de las nueve plantillas Jinja.
- Respuesta correcta de inicio, catálogo, novedades, detalle de producto, carrito, acceso administrativo y panel autenticado.
- Búsqueda y filtro por categoría.
- Agregar, actualizar y eliminar del carrito.
- Formulario de checkout, registro de un pedido de prueba, total y descuento de existencias.
- Descarga del resumen de pedido y catálogo en PDF.
- Disponibilidad de CSS, JavaScript, logotipo e imágenes nuevas.
- Comparación contra Git: servidor, generadores PDF, dependencias, logotipo original, enlaces de navegación y formularios de productos sin modificaciones.
- `node --check static/js/main.js` y `git diff --check` sin errores.

Limitación: la herramienta de navegador no estuvo disponible; falta confirmar visualmente el diseño y los gestos del menú en un navegador de escritorio y en dispositivos móviles. Las pruebas de servidor no sustituyen esa comprobación. No se realizó un despliegue.

## Instalación

El ZIP contiene los seis archivos completos de la actualización y este informe. Copiarlos sobre sus mismas rutas en la aplicación y publicar mediante el procedimiento habitual. No requiere dependencias, migraciones ni cambios de configuración.

## Fondo generado

Se usó la herramienta integrada de generación de imágenes, sin llamadas API desde la aplicación. Fotografía ilustrativa de variedad comercial; no representa inventario ni disponibilidad reales.

Prompt utilizado:

> Use case: ads-marketing. Asset type: wide photographic background for the home hero of a Paraguayan general merchandise store. Create a professional high resolution landscape product still life. Assortment on the RIGHT half: tasteful navy urban bicycle, folded camping chair and canvas tent, stainless steel vacuum thermos, ceramic bowls, cooking pot, wicker storage basket and neutral baby stroller. Realistic proportions, clean high quality commercial photography, warm natural side light, navy and warm sand palette with restrained golden details, calm modern showroom, no people. LEFT 50 percent is uncluttered dark navy wall with subtle natural texture for white website text to be overlaid in HTML. Composition wide approximately 16:9. No words, no logos, no watermark. Products are illustrative assortment, not actual catalog items.
