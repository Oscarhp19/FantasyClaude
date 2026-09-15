# Panel siempre disponible, con el PC apagado

GitHub ejecuta el pipeline cada 15 minutos en sus servidores y publica la
página en [Oscarhp19/FantasyClaude](https://github.com/Oscarhp19/FantasyClaude).
Tu ordenador no pinta nada: puede estar apagado.

## Puesta en marcha: un comando

Desde `fantasy/`:

```bash
python configurar_github.py
```

Te va a pedir dos cosas, y nada más:

1. **Autorizar GitHub.** Si tu credencial ha caducado se abre una ventana: inicia
   sesión y pulsa *Authorize*.
2. **Tu email y contraseña de LaLiga.** Se comprueban contra LaLiga antes de
   guardarlas, así que una errata se detecta en el momento y no quince minutos
   después con el robot fallando.

El resto lo hace solo: sube el código, guarda los tres secretos cifrados
(`LALIGA_EMAIL`, `LALIGA_PASSWORD`, `RUTA_SECRETA`), activa Pages, lanza la
primera actualización, espera a que termine e imprime tu URL. También la deja en
`data/panel_url.txt`, que no se sube al repositorio.

Tus contraseñas se teclean en tu terminal y viajan cifradas directamente a
GitHub. No se escriben en disco ni pasan por ningún chat.

Se puede relanzar sin miedo: reutiliza la ruta secreta de la vez anterior, así
que la URL no cambia.

## Qué tener en cuenta

**No es una contraseña.** Cualquiera con la URL ve tu panel. La ruta es un
secreto, no aparece en el repositorio aunque sea público, y la página lleva
`noindex`, así que no la encontrará un buscador. Pero si compartes el enlace,
compartes los datos.

**El cron se retrasa.** GitHub no garantiza la puntualidad de los `schedule`:
cuando hay carga, los 15 minutos pueden ser 20.

**Se apaga solo a los 60 días.** GitHub desactiva los workflows programados en
repos sin actividad durante dos meses. Te avisa por correo y se reactiva con un
clic.

**Tu contraseña de LaLiga está en GitHub.** Cifrada, en tu cuenta, y no aparece
en los logs. Si deja de convencerte, borra los secretos en *Settings → Secrets
and variables → Actions* y el robot se para.

## Si algo falla

En [Actions](https://github.com/Oscarhp19/FantasyClaude/actions) verás la
ejecución en rojo. Si cambias la contraseña de LaLiga, vuelve a lanzar
`configurar_github.py`: actualiza los secretos y mantiene la URL.
