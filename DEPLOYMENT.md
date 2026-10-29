# Publicar Samudio Hnos.

## 1. Subir a GitHub

Desde esta carpeta, crea un repositorio vacío en GitHub, sin README adicional.
Si usas la carpeta original, inicializa Git si aún no está inicializado:

```powershell
git init -b main
git add .
git status
git commit -m "Prepare Samudio Hnos. storefront for deployment"
git remote add origin https://github.com/victorsam123/hnos_samudios_representaciones.git
git push -u origin main
```

Si descargaste el ZIP preparado, extráelo en una carpeta nueva y ejecuta los
mismos comandos. Comprueba que `.env`, `instance`, `tmp` y `venv` no aparezcan
en los archivos que se van a subir. `.env.example` sí debe incluirse.

## 2. Crear el servicio en Railway

1. Crea un proyecto y elige desplegar desde el repositorio de GitHub.
2. Usa la raíz del repositorio como directorio del servicio. Railway construirá
   el `Dockerfile`; `railway.json` configura Gunicorn y la comprobación de `/`.
3. **Antes de cargar datos, crea un volumen y móntalo en `/app/instance`.**
   Esta ruta conserva `store.db` y `uploads` entre despliegues. Configura una
   sola réplica para este esquema con SQLite y volumen local.
4. Configura las variables del servicio:

| Variable | Valor |
| --- | --- |
| `SECRET_KEY` | Secreto aleatorio largo, privado y persistente |
| `ADMIN_USERNAME` | Tu usuario administrador |
| `ADMIN_PASSWORD` | Tu contraseña privada |
| `WHATSAPP_NUMBER` | `595983620676`, o tu número internacional sin `+` |
| `DATABASE_URL` | `sqlite:////app/instance/store.db` |
| `COOKIE_SECURE` | `true` |
| `FLASK_DEBUG` | `false` |

Railway proporciona `PORT`; Gunicorn lo lee automáticamente y escucha en
`0.0.0.0`. No subas `.env` al repositorio ni lo copies a la imagen.
Genera el secreto desde un Python instalado y guarda el resultado únicamente
en las variables privadas del servicio:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

5. Despliega y genera el dominio HTTPS desde la configuración de red.
6. Verifica inicio, catálogo, inicio de sesión en `/admin`, carga de imágenes,
   carrito, pedido y descarga PDF. Reinicia el servicio y comprueba que los
   productos y las imágenes permanezcan. Conserva el mismo `SECRET_KEY` para
   mantener válidos los enlaces privados de los pedidos.

## 3. Datos existentes y copias

Un despliegue nuevo comienza sin los productos y pedidos de tu ordenador.
Para conservarlos, detén las escrituras, respalda `instance/store.db` y
`instance/uploads`, y transfiere ambos por un canal privado al volumen del
servicio antes de usarlo. No publiques bases ni imágenes de clientes en GitHub.
Activa copias del volumen y verifica su restauración.

Si eliges PostgreSQL, configura `DATABASE_URL` con la referencia privada del
servicio PostgreSQL de Railway. Mantén el volumen para las imágenes. Cambiar la
URL no migra los registros de SQLite: esa migración debe realizarse aparte.

## 4. Probar el contenedor localmente (opcional)

Con Docker instalado y un `.env` local configurado:

```powershell
docker build -t samudio-hnos .
docker run --rm -p 8080:8080 --env-file .env -e COOKIE_SECURE=false -e DATABASE_URL=sqlite:////app/instance/store.db -v samudio-data:/app/instance samudio-hnos
```

Abre <http://localhost:8080>. Gunicorn se ejecuta dentro de Linux; para
desarrollo local en Windows puedes seguir usando `python app.py`.

Referencias oficiales: [Flask en Railway](https://docs.railway.com/guides/flask),
[volúmenes persistentes](https://docs.railway.com/volumes) y
[puerto del servicio](https://docs.railway.com/networking/troubleshooting/application-failed-to-respond).
