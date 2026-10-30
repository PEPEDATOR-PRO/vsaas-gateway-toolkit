# Instrucciones del proyecto

- Mantener los datos de cada equipo en perfiles ignorados por Git. No incluir PSK, tokens, claves SSH ni registros reales en código o fixtures.
- El código fuente vive en `src/`; los instaladores de `dist/` son generados por `tools/build.py`.
- Las pruebas no deben instalar servicios, ejecutar Docker real ni acceder a dispositivos de clientes. Usar simulaciones y directorios temporales.
- Verificar Python con unittest y las interfaces con `npm run test:ui`. Generar los paquetes antes de entregar cambios de instalación.
- Conservar consulta bajo demanda y detención de lectores al ocultar paneles.
- Distinguir configuración, proceso activo, transporte TCP y transmisión de video confirmada. No declarar nube online a partir de señales locales.
- Mantener la adaptación de Vista global reversible y separada de los archivos del paquete de Ubuntu.
- Las credenciales se introducen en el equipo de destino, no mediante argumentos ni archivos versionados.
