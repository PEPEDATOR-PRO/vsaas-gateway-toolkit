# Paquete de instalación VXG 1.0.16

Importado de `docker_gateway_package_1.0.16_261013.zip`, proporcionado para este proyecto. `package.json` registra el hash SHA256 del archivo original y los hashes de sus scripts.

Se conservan los scripts del proveedor, Compose y los archivos de versión como referencia. Se normalizaron los finales de línea para Git. El `.env` original contiene un token de registro y está excluido; `.env.example` conserva los parámetros de conexión y deja vacíos el usuario y el token.

Las imágenes Docker no están en el ZIP ni en este repositorio. Se descargan del registro autenticado del proveedor para ARM64 o x64, con las versiones fijadas en los archivos `.version`.

## Instalación recomendada

Desde la raíz del toolkit, en Ubuntu con Docker instalado:

```bash
sudo python3 scripts/install.py vxg
```

El módulo solicita las credenciales del registro y una contraseña nueva para el administrador VXG. No necesita todavía un perfil de VPN. Consulta [la guía completa](../../../docs/INSTALACION-VXG.md).

El toolkit utiliza el Compose revisado, pero no ejecuta automáticamente `start.sh`, `env_setup.sh`, `update.sh` ni `stop.sh` del proveedor. El módulo de instalación genera las claves Django con Python, mantiene las credenciales del registro fuera del entorno de la aplicación y usa una configuración temporal de Docker para descargar las imágenes.

Este módulo es para equipos nuevos. Las actualizaciones de un despliegue con cámaras requieren planificar respaldo, migración y validación aparte. No se asigna una licencia nueva a los archivos del proveedor.
