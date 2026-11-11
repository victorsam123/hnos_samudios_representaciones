# Gestión de Vendedores — Samudio Hnos.

## Acceso y uso

El propietario mantiene sus credenciales y su acceso existente en `/admin`. Desde allí entra a **Gestión de Vendedores** (`/admin/vendedores`) para crear cuentas, editar nombres y usuarios, activar/desactivar cuentas y cambiar contraseñas. El acceso de vendedores está en `/vendedor/ingresar`, también enlazado desde el pie de la tienda.

El administrador original se autentica mediante la configuración existente del servidor, no mediante una tabla de usuarios. Se conserva ese mecanismo. Las cuentas nuevas tienen el rol `vendedor`; los formularios no permiten asignar privilegios administrativos. Las contraseñas de vendedores se almacenan con scrypt mediante Werkzeug; no se guardan ni se muestran en texto plano. Se exigen 12–128 caracteres y al menos tres grupos de caracteres. Se limitan los intentos fallidos a ocho por combinación de dirección de conexión y usuario en una ventana de quince minutos. Desactivar, editar el acceso o cambiar la contraseña invalida las sesiones anteriores.

Cada vendedor dispone de su panel con fecha/hora de Paraguay, Nuevo pedido, Catálogo, Carrito comercial, Mis pedidos y Cerrar sesión. Puede registrar un comercio con nombre obligatorio y datos opcionales, o reutilizar una ficha de su propia cuenta. No se modifican fichas de clientes existentes. Un nombre de comercio equivalente, sin distinguir mayúsculas ni espacios repetidos, reutiliza la ficha anterior dentro de la misma cuenta.

Se mantiene **un pedido en preparación por vendedor**, persistido en PostgreSQL. Es necesario confirmar el vaciado de un carrito con artículos antes de cambiar de comercio. Los formularios de una pestaña antigua no pueden modificar el carrito de otro comercio. El carrito público usa su mecanismo original y permanece separado.

El catálogo comercial utiliza los productos activos reales y las mismas imágenes, categorías, descripciones, precios y existencias de la tienda. Incluye búsqueda, filtro por categoría y paginación. No se insertan productos de ejemplo, vendedores ni contraseñas predeterminadas al instalar.

## Confirmación y stock

La pantalla Resumen del pedido comercial permite revisar comercio, vendedor, fecha/hora, productos, cantidades, precios, subtotales, observaciones y total. El número se asigna al registrar.

Al confirmar, el servidor vuelve a validar la cuenta, el comercio, las cantidades, los productos activos, los precios y el stock. Si cambió un precio o el carrito, se exige una nueva revisión. El cliente no determina los importes. Se bloquean las filas de vendedor y productos y se realiza el descuento condicional de existencias en la misma transacción que el pedido y sus artículos.

Una clave única por borrador evita registrar o descontar dos veces al repetir o enviar simultáneamente la confirmación. Si la respuesta de red es incierta, se puede consultar el historial y repetir la misma confirmación sin duplicar el pedido. Los fallos revierten los cambios no confirmados, incluidos el cliente de ese pedido, sus artículos y los movimientos de stock.

Se reutilizan `Order` y `OrderItem`. Se crea una ficha `Customer` para la instantánea de cada pedido comercial, siguiendo el comportamiento de los pedidos existentes, sin actualizar ni eliminar clientes anteriores. `SalesOrder` relaciona ese pedido con vendedor y comercio, y conserva sus nombres, datos y nombres/precios históricos de productos. Los cambios posteriores de nombre no alteran el resumen comercial.

El pedido comienza como **Pendiente**, descuenta stock una vez y queda identificado como **Pedido comercial** en la administración general. Se conserva la regla existente de estados: cambiar el estado no descuenta nuevamente ni repone automáticamente existencias al cancelar. No se añadieron nuevas reglas de inventario para cancelaciones.

## Historial, administración e impresión

Los vendedores solo pueden consultar sus propios pedidos; no pueden modificarlos, eliminarlos ni cambiar sus estados. El historial permite buscar por comercio y filtrar por fechas de Paraguay. La administración puede filtrar adicionalmente por vendedor y estado, consultar los comercios registrados y utilizar el control de estado existente.

Los indicadores distinguen pedidos registrados, pendientes, confirmados y cancelados, comercios con pedidos e importe acumulado. El importe acumulado incluye todos los estados, también cancelados. **No se lo presenta como dinero cobrado.** El sistema original no registra cobros ni define reconocimiento de ventas; el indicador de ventas reconocidas informa que no está disponible, en vez de inventar una equivalencia con Pendiente, Confirmado o Entregado.

Se incluyen impresión del resumen y descarga PDF A4 con nombre comercial, número de pedido, fecha/hora con segundos en Paraguay, vendedor, comercio, responsable y contacto, tabla de artículos, total, estado, observaciones y teléfono 0983620676. El PDF comercial usa las instantáneas guardadas, también al descargarlo desde el panel general. No es una factura legal ni prueba de pago o entrega.

## Arquitectura y archivos

- `extensions.py`: instancia compartida de SQLAlchemy y CSRF, sin cambiar el esquema original.
- `sales_models.py`: siete tablas adicionales: cuentas, comercios, carritos, artículos de carrito, vínculo/instantáneas del pedido, auditoría y control de intentos de acceso.
- `sales.py`: blueprint de vendedores y administración comercial, autorización, validaciones, cálculo de importes y transacciones.
- `sales_pdf.py`: generador A4 comercial.
- `templates/sales/`, `static/css/sales.css`, `static/js/sales.js`: interfaz comercial responsive e impresión.
- `migrations/`: configuración Flask-Migrate/Alembic, línea base `0001_legacy` y migración aditiva `0002_sales`.
- `tests/test_sales.py`: pruebas comerciales y de migraciones. `tests/test_admin_products.py` conserva la batería administrativa y prepara las migraciones de la base aislada.
- Integración mínima en `app.py`, `templates/base.html` y `templates/admin.html`: registro del módulo, enlaces, identificación de pedidos comerciales, PDF y auditoría de estados. La hoja de estilos pública y las plantillas de catálogo, carrito y checkout se conservan.
- `requirements.txt`: agrega Flask-Migrate. `railway.json`: ejecuta `flask --app app db upgrade` como paso previo al despliegue.

Todas las mutaciones usan POST y CSRF. La autorización se comprueba en el servidor, incluyendo la propiedad de comercios y pedidos. No hay endpoints comerciales para modificar productos, precios, existencias, roles o pedidos confirmados. Las respuestas comerciales y documentos llevan `Cache-Control: no-store, private`. Se registran operaciones relevantes sin contraseñas en `SalesAudit`. Los instantes se almacenan en UTC y se presentan en `America/Asuncion`.

Se conservaron además las mejoras administrativas pendientes que ya estaban en el espacio de trabajo: tema oscuro y gestión segura de fotos y productos. No se sustituyó ni reconstruyó el proyecto.

## Migración y puesta en marcha

Antes de aplicar en producción, realizar una copia de PostgreSQL y del almacenamiento de imágenes y ensayar la misma versión en un entorno de prueba. Mantener el mismo `DATABASE_URL`, `SECRET_KEY`, credenciales administrativas y volumen de imágenes. No reemplazar `.env`, `instance/` ni archivos subidos.

En un entorno con Python y las variables correspondientes:

```text
python -m pip install -r requirements.txt
flask --app app db upgrade
flask --app app db current
```

El resultado esperado es `0002_sales (head)`. La línea base reconoce las seis tablas originales cuando existen y no las recrea ni borra sus filas. Si solo encuentra parte del esquema original, se detiene para revisión. Las tablas comerciales se crean mediante Flask-Migrate; el módulo no las genera silenciosamente al atender una solicitud. Se conserva el arranque heredado de las tablas originales.

No usar `db.create_all()` como sustituto de estas migraciones ni hacer `stamp head` sobre una base que no tenga las tablas comerciales. No ejecutar `downgrade` para intentar desinstalar: las revisiones rechazan degradaciones destructivas. Para revertir la interfaz se puede volver al código anterior conservando las tablas aditivas; un cambio de datos exige una migración revisada o restauración planificada.

En Railway, el nuevo `preDeployCommand` aplica las migraciones usando el PostgreSQL indicado por `DATABASE_URL` antes de iniciar los nuevos procesos. Si ese comando falla, el despliegue no continúa. No se usan archivos ni volúmenes para las tablas comerciales. Ver [comandos previos al despliegue](https://docs.railway.com/deployments/pre-deploy-command) y [configuración de Railway](https://docs.railway.com/config-as-code/reference). En otros alojamientos, ejecutar el mismo comando como paso de release antes de habilitar la nueva versión.

## Pruebas realizadas y límites

La batería tiene **30 pruebas**. En SQLite en memoria pasan 28 y se omiten las dos que necesitan bloqueos PostgreSQL. En PostgreSQL 18 temporal pasan las 30, incluidas concurrencia de stock y confirmación duplicada simultánea. La instancia de prueba utiliza credenciales aleatorias, solo escucha en localhost y se detiene al terminar. No se conectó a producción durante estas verificaciones.

Cobertura: creación y edición de cuentas, hash de contraseñas, reinicio de contraseñas, activación y revocación de sesiones; acceso por rol y CSRF; límite de intentos; comercio obligatorio y reutilización; catálogo y filtros; cantidades válidas e inválidas; carritos públicos y comerciales separados; pestañas antiguas; total calculado en servidor; precios/stock cambiados; transacciones fallidas; historial privado; nombres históricos; fecha y filtros de Paraguay; consulta administrativa y auditoría de estados; PDF; preservación de datos al adoptar el esquema; correspondencia exacta entre migraciones y modelos; el botón «Acceso vendedor» inmediatamente después de «Acceso administrador» dentro del banner y su destino de inicio de sesión; y las doce pruebas administrativas anteriores.

También se ejecutó la regresión del flujo público completo: búsqueda, filtros, agregar/actualizar/eliminar del carrito, checkout, total, descuento de stock y PDFs. El JavaScript pasa `node --check`; `git diff --check` no informa errores. Los errores de base de datos y almacenamiento que aparecen en logs de pruebas son fallos simulados para verificar rollback y mensajes.

Se generó un PDF de demostración de dos páginas con datos exclusivamente de prueba y se inspeccionaron sus páginas renderizadas: tabla, encabezado repetido, total, observaciones y pie sin recortes ni superposiciones. Ese PDF de prueba no se carga en la tienda.

**Límite pendiente:** el servicio de navegador de esta sesión no está disponible. La interfaz tiene estilos móviles y sus plantillas/formularios se ejercitaron, pero falta la comprobación visual e interacción en un navegador de escritorio y un celular real. No se afirma que esa prueba visual ni una prueba de impresión en una impresora física se hayan realizado.

Las verificaciones no aplicaron migraciones a producción. La publicación del código en GitHub no sustituye la comprobación del despliegue y de la versión servida por el dominio. El ZIP entrega el código fuente completo, migraciones, pruebas y documentación, sin bases de datos, `.env`, credenciales ni archivos de clientes.

Para repetir pruebas en un proceso separado: `python -m unittest discover -s tests -v`. Por defecto utiliza SQLite en memoria. `ADMIN_TEST_DATABASE_URL` permite exclusivamente una base desechable del rol `admin_test`; nunca apuntarla a la base comercial.

Referencias técnicas: [Flask-Migrate](https://flask-migrate.readthedocs.io/en/latest/), [hashes de Werkzeug](https://werkzeug.palletsprojects.com/en/stable/utils/), [transacciones SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).
