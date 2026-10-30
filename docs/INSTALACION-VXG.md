# Instalar VXG desde cero

## 1 Comprobar Ubuntu y Docker

El flujo inicial se preparó para Raspberry Pi 5 con Ubuntu 26.10 ARM64. Comprueba arquitectura y red:

```bash
cat /etc/os-release
uname -m
ip -4 addr
ip -4 route
```

En Ubuntu con esos paquetes disponibles, instala Docker y Compose:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git curl ca-certificates unzip
sudo systemctl enable --now docker
sudo docker compose version
sudo docker run --rm hello-world
```

Si hay un error, resuélvelo antes de iniciar VXG. No mezcles otra instalación de Docker con una existente sin revisarla.

## 2 Obtener el repositorio privado

Si aún no tienes una copia:

```bash
sudo apt install -y gh
gh auth login --hostname github.com --git-protocol https --web
gh repo clone PEPEDATOR-PRO/vsaas-gateway-toolkit
cd ~/vsaas-gateway-toolkit
```

Para actualizar una copia existente, autoriza GitHub si hace falta y ejecuta desde su carpeta:

```bash
gh auth setup-git
git pull --ff-only
```

Cuando termine la descarga, puedes retirar la sesión local de GitHub con `gh auth logout --hostname github.com`. Para futuras actualizaciones privadas hará falta autorizar de nuevo o configurar un acceso específico del equipo.

## 3 Proporcionar credenciales del registro de VXG

El paquete original incluye un `.env` con `GITLAB_REGISTRY_USER` y `GITLAB_REGISTRY_TOKEN`. Esas credenciales son para el registro de imágenes de VXG, no para GitHub. El archivo original se conserva fuera del repositorio.

La opción más simple es abrir el archivo original localmente y proporcionar usuario y token cuando los solicite el instalador. El token se introduce sin mostrarse en pantalla. No hace falta copiarlo al chat ni guardarlo en el perfil del equipo.

Como alternativa, coloca el `.env` del proveedor en un archivo privado en Ubuntu, fuera del proyecto, y restringe sus permisos:

```bash
chmod 600 ~/vxg-registry.env
```

No uses como archivo privado la plantilla vacía que viene en Git. El archivo debe tener las credenciales entregadas por el proveedor.

## 4 Revisar e instalar

Primero consulta lo que hará el módulo:

```bash
python3 scripts/install.py vxg --dry-run
```

Después elige una de estas formas:

```bash
# Introducir usuario y token de forma interactiva
sudo python3 scripts/install.py vxg

# O leerlos desde un archivo privado que ya preparaste
sudo python3 scripts/install.py vxg --vxg-env ~/vxg-registry.env
```

El instalador detecta ARM64 o x64, usa VXG 1.0.16, solicita una contraseña nueva de administrador de al menos 12 caracteres y genera las claves Django. En esta primera versión del módulo, la contraseña no admite comillas simples ni barras invertidas.

La configuración de Docker utilizada para el login es temporal. El token del registro no se escribe en el `.env` de la aplicación ni se pasa al contenedor. Si proporcionas un archivo privado propio, ese archivo permanece bajo tu control y no se elimina automáticamente.

El despliegue queda en `/opt/vsaas-gateway/vxg/1.0.16/`; su `.env` tiene permisos restringidos y contiene los secretos locales de la aplicación. El módulo rechaza un proyecto o directorio que ya exista para evitar sustituir un Gateway en uso.

## 5 Validar

```bash
sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Abre `http://IP_LOCAL_DEL_GATEWAY` e inicia sesión con el usuario `admin` y la contraseña que elegiste. Confirma que la interfaz carga correctamente y registra el nuevo Gateway en tu plataforma mediante el procedimiento de VXG. Añade una cámara y comprueba el video desde la nube.

Después sigue [la instalación de administración](INSTALACION.md) para configurar una identidad VPN nueva, SSH, Cockpit y los paneles.

## Si no termina

- Si falla la autenticación antes de descargar, corrige usuario y token. No se habrá creado el directorio de despliegue.
- Si falla una descarga o el arranque después de crear el directorio, se conservan los archivos para diagnóstico. No borres volúmenes ni repitas una instalación de cero sobre un servicio con datos.
- El módulo y sus límites se probaron con simulaciones. El arranque de este nuevo flujo de instalación debe validarse en el equipo nuevo antes de considerarlo una receta de campo comprobada.
