# Wilson Samudio Representaciones

Tienda web Flask en español. Incluye catálogo con categorías y búsqueda,
carrito de compras, registro de pedidos, contacto por WhatsApp y administración
de productos, novedades y pedidos.

## Requisitos

- Python 3.10 o superior
- pip

## Instalación local

1. Crea y activa un entorno virtual:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Instala las dependencias:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Copia `.env.example` como `.env` y configura `ADMIN_USERNAME`,
   `ADMIN_PASSWORD` y un `SECRET_KEY` aleatorio y privado. Conserva tu archivo
   `.env` actual si ya tienes configurado el acceso. Las credenciales de ejemplo
   son marcadores y deben sustituirse antes de publicar.

4. Inicia el sitio:

   ```powershell
   python app.py
   ```

   Abre <http://127.0.0.1:5000>. La base SQLite y sus tablas se crean en la
   carpeta `instance` al iniciar la aplicación.

La tienda empieza con las categorías predefinidas y sin productos. Inicia
sesión en `/admin` para registrar los productos, publicar novedades y gestionar
los pedidos. Los pagos y la entrega se coordinan directamente con el negocio;
no se procesa información de tarjetas.

Desde la sección **Categorías** del panel administrativo puedes agregar nuevas
categorías. Quedan guardadas y aparecen, en orden alfabético, en el inicio,
el filtro del catálogo y el formulario de productos al cargar o actualizar la
página. No se permiten nombres vacíos ni categorías repetidas.

## Configuración

Las fechas y horas visibles usan la zona `America/Asuncion` (Paraguay),
incluidos los pedidos y sus resúmenes PDF. La base conserva las fechas en UTC;
la conversión también se aplica a los registros existentes. La dependencia
`tzdata` proporciona las reglas horarias en Windows.

Al finalizar una compra, el cliente puede descargar un resumen PDF con sus
datos, los productos, las cantidades, los precios registrados y el total.
El enlace privado permite acceder únicamente a ese pedido; conserva un
`SECRET_KEY` persistente para que los enlaces sigan funcionando después de
reiniciar. En **Pedidos recibidos**, el administrador puede descargar el mismo
resumen de cada pedido. El resumen no acredita el pago.

Las imágenes de productos y novedades se seleccionan desde el ordenador en el
panel administrativo. Se aceptan JPG, PNG, WEBP y GIF de hasta 5 MB; la imagen
es opcional. Los archivos se guardan en `instance/uploads` y se muestran en la
tienda sin cambiar la estructura de la base de datos. Las imágenes registradas
anteriormente mediante URL siguen funcionando. Incluye `instance/uploads` en
las copias de seguridad y conserva esta carpeta al actualizar el sitio.

`DATABASE_URL` acepta SQLite de forma predeterminada o PostgreSQL usando una
URL `postgresql://`. `WHATSAPP_NUMBER` debe contener el número internacional
solo con dígitos, sin `+` ni espacios. En producción, usa HTTPS, activa
`COOKIE_SECURE`, establece un `SECRET_KEY` persistente y no publiques el archivo
`.env`.


## Identidad visual

Logo original de Samudio Hnos. en `static/img/logo-samudio-hnos.png`.
La interfaz usa `static/img/logo-samudio-hnos-transparente.png`, sin fondo
blanco y centrado, sin inclinaci?n ni tarjeta de fondo.
La interfaz combina azul marino y acentos dorados con Manrope, alojada
localmente para no depender de Google Fonts. Su licencia se incluye en
`static/fonts/OFL-Manrope.txt`. El dise?o se adapta a escritorio y m?vil.
Los cambios visuales conservan las rutas, formularios y l?gica de la tienda.

## GitHub y Railway

Consulta [DEPLOYMENT.md](DEPLOYMENT.md) para subir el proyecto a GitHub y
configurar Railway con almacenamiento persistente. Se incluyen `Dockerfile`,
`railway.json` y `gunicorn.conf.py` para el arranque de producci?n.
La base local, im?genes cargadas, `.env`, entornos y temporales est?n excluidos
de Git y de la imagen Docker. Los datos existentes requieren una transferencia
privada; no se suben al repositorio.
