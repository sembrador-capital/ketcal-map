# Logos de exportadoras

El mapa los busca por el `id` del receptor que emite `tools/build_cosecha.py`:

```
assets/exportadoras/rosales.png
assets/exportadoras/gesex.png
assets/exportadoras/propal.png
assets/exportadoras/el_parque.png
assets/exportadoras/westfalia.png
assets/exportadoras/rio_blanco.png
assets/exportadoras/inversion_cordillera.png
```

Nombre de archivo = `id` del receptor + `.png`. El `id` sale de `RECEPTORES` en
`tools/build_cosecha.py`; si aparece una exportadora nueva, el script le genera
un `id` con el mismo criterio (minúsculas, sin acentos, espacios a `_`) y basta
dejar el archivo con ese nombre.

**Formato**: PNG con fondo transparente, alto de 48 a 96 px (se muestra a 22 y a
26 px de alto, así que con 2× alcanza).

**Sin márgenes propios.** La caja del mapa mide 58×22 px y ajusta con
`object-fit: contain`, así que todo el aire que traiga el archivo se descuenta
del tamaño útil: El Parque llegaba ocupando el 50 % de su lienzo y se veía la
mitad de grande de lo que podía. Después de dejar un archivo nuevo:

```bash
python tools/trim_logos.py
```

Recorta el margen vacío —transparente o casi blanco, porque no todos los
archivos traen canal alfa— sin reescalar ni recomprimir la marca. Es idempotente:
un archivo ya al ras se deja como está. El aire alrededor lo pone el CSS, que es
donde corresponde: así es el mismo para todos.

**Si el archivo no está**, el `onerror` del `<img>` lo quita del DOM y aparece un
monograma con las iniciales sobre el color de la porción. La pestaña funciona
igual; los logos sólo la hacen más legible de un vistazo.
