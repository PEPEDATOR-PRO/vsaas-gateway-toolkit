# Mantenimiento y versiones

## Fuente única

Edita archivos de `src/`, `scripts/`, `config/equipo.example.json` y `docs/`. Genera los instaladores con `python3 tools/build.py`; no edites el contenido incrustado en `dist/` porque se sustituye al generar de nuevo.

## Comprobaciones antes de publicar

```bash
python3 -m unittest discover -s src -p 'test_*.py'
python3 -m unittest discover -s scripts -p 'test_*.py'
npm ci
npx playwright install chromium
npm run test:ui
python3 tools/build.py
```

Revisa además la instalación en un Gateway de pruebas, el acceso después de reiniciar y el resultado con cámaras transmitiendo. Los tests de navegador usan datos simulados.

En cada versión actualiza `VERSION`, `package.json` y `CHANGELOG.md`. Crea una etiqueta Git después de las verificaciones y distribuye una copia de esa etiqueta o sus instaladores junto a `SHA256SUMS`. Una versión de instalación no debe depender de cambios que aún no se hayan confirmado en Git.

## Vista global de Cockpit

La adaptación se instala en `/usr/local/share/cockpit/vsaas_system`, enlaza los recursos del paquete nativo y modifica una copia de su índice. Los archivos del paquete de Ubuntu se conservan. El instalador reconoce la estructura esperada y se detiene si no coincide.

Después de actualizar Cockpit, comprueba Vista global y reaplica `resumen` si es necesario. Para retirarla, mueve la carpeta de adaptación fuera de las carpetas de paquetes y vuelve a iniciar sesión:

```bash
sudo mv /usr/local/share/cockpit/vsaas_system "/var/backups/vsaas-overview-retirado-$(date +%Y%m%d-%H%M%S)"
```

Las versiones anteriores de la adaptación y los paneles se guardan en `/var/backups/` cuando el instalador los sustituye. Retirar las tarjetas no elimina los paneles separados.

## Repositorio público

La descarga HTTPS y `git pull --ff-only` no requieren autenticación en un repositorio público. Los accesos del registro VXG y del FortiGate siguen siendo independientes y privados. La automatización solo prueba y genera paquetes; no instala en Gateways.

Los perfiles reales, PSK, claves SSH, capturas de clientes e informes operativos deben mantenerse fuera del historial. Un repositorio privado no sustituye ese control. Se conservan los scripts recibidos de VXG como referencia de versión; las imágenes y el `.env` original con credenciales no se publican.

Los parámetros centrales se preparan en `config/vpn-central.json` (ignorado). En la versión pública actual no se fija un servidor VPN ni una plataforma de cliente. El asistente mantiene las tres entradas por equipo tras esa preparación. El módulo VXG solicita el host API si no fue proporcionado localmente. Equipos ya instalados no se reconfiguran por hacer `git pull`.

Las primeras revisiones del proyecto contienen direcciones de infraestructura que se retiraron de la versión actual. Quitarlas de un archivo no las elimina del historial publicado. Esta actualización no reescribe el historial. No publiques informes de clientes para documentar las pruebas; utiliza resultados agregados sin identificadores.
