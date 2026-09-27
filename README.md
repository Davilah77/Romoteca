# Romoteca

Romoteca es un inventario seguro y sencillo para colecciones de ROMs. Su objetivo
es cargar un archivo DAT, escanear una carpeta elegida por el usuario y mostrar
qué juegos están completos, incompletos o ausentes.

## Principios

- Solo lectura: Romoteca no mueve, renombra ni elimina ROMs.
- Ninguna ruta personal forma parte del proyecto.
- Las carpetas se eligen desde la aplicación.
- Los resultados explican si proceden del DAT o del escaneo local.

## Versión 0.1

- DAT XML de estilo Logiqx/ClrMamePro y listas `machine`/`game`.
- Archivos sueltos y contenido de ZIP.
- Comparación por SHA-1 o por CRC32 y tamaño.
- Inventario de CHD, RAR y 7Z como archivos no verificados.
- Filtros para juegos completos, incompletos y ausentes.
- Exportación de un informe CSV.

## Ejecutar desde el código

Requiere Python 3.11 o posterior.

```powershell
py main.py
```

## Crear el ejecutable

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

El resultado se guarda en `dist\Romoteca.exe`.

## Versiones

- Correcciones y ajustes: `0.1.1`, `0.1.2`, etc.
- Funciones nuevas importantes: `0.2.0`, `0.3.0`, etc.

