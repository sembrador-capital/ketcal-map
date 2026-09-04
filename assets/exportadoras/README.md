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

**Formato**: PNG con fondo transparente, alto de 48 a 96 px (se muestra a 19 y a
24 px de alto, así que con 2× alcanza). Sin márgenes propios: la caja del mapa ya
pone su padding.

**Si el archivo no está**, el `onerror` del `<img>` lo quita del DOM y aparece un
monograma con las iniciales sobre el color de la porción. La pestaña funciona
igual; los logos sólo la hacen más legible de un vistazo.
