# Fantasy — análisis de mercado LaLiga Fantasy Oficial

Lee el mercado diario de tu liga y te dice qué comprar, hasta cuánto pujar y qué
cláusulas tuyas están a tiro, cruzando dos fuentes que se complementan:

- **API oficial de LaLiga Fantasy** — tu mercado, tu dinero, los movimientos de
  la liga, el valor oficial y la media de puntos. Requiere conectar tu cuenta
  una vez (ver *Conectar tu cuenta*).
- **[FútbolFantasy](https://www.futbolfantasy.com)** — tendencia de precio y
  probabilidad de alineación, que la API oficial no publica. Público, sin cuenta.

`analiza.py` funciona solo con la segunda, sin conectar nada, si prefieres
teclear los nombres a mano.

## Uso diario

```bash
python servidor.py
```

Levanta el panel, lo refresca cada 15 minutos y añade un botón **Actualizar**
que rehace los datos al momento. Al arrancar imprime dos direcciones: una para
este ordenador y otra para el móvil, que tiene que estar en la misma wifi.

```
  este equipo   http://localhost:8000
  iPhone / iPad http://192.168.1.XX:8000   (misma wifi)
```

Opciones: `--puerto 8080`, `--cada 30` (minutos), `--sin-refresco`.

La primera vez, Windows preguntará si permites que Python acepte conexiones en
la red privada: hay que decir que sí o el móvil no llegará.

### A mano, sin servidor

```bash
python sync.py && python informe.py && python vista.py
```

Tres pasos: `sync.py` baja tu liga real, `informe.py` la cruza con la tendencia
de FútbolFantasy y `vista.py` genera `vista.html`, una página autónoma que se
abre en el navegador o se publica tal cual.

El cruce de nombres entre las dos fuentes tiene truco: la API oficial abrevia
(`O. Sancet`, `Á. Valles`) y FútbolFantasy no. Se intenta el nombre completo y,
si no casa, el apellido filtrado por equipo real. Los que se queden sin
emparejar salen listados al final en vez de perderse.

### Análisis suelto, sin la liga

```bash
python analiza.py Dmitrovic "Marcos Alonso" Yeremay Pedrosa
```

O escribiendo los nombres en `mercado_hoy.txt` (uno por línea, `#` para comentar):

```bash
python analiza.py -f mercado_hoy.txt --saldo 12000000
```

Opciones:

| Flag | Qué hace |
|---|---|
| `-f FICHERO` | lee los nombres de un fichero |
| `--saldo N` | avisa si las pujas recomendadas no caben en tu presupuesto |
| `--json F` | vuelca el informe a JSON (para que Claude lo lea) |
| `--refresh` | fuerza la descarga del mercado aunque la caché esté fresca |

El mercado se cachea en `data/mercado.json` y se refresca solo cuando pasa de
12 horas, así que la primera ejecución del día tarda algo más.

## Cómo decide

**Puntos esperados** = media de puntos cuando juega × probabilidad de alineación.

**Tendencia**: compara la variación a 7 días con la de 14. Si la caída reciente
es peor que la previa, el valor está *acelerando* hacia abajo y entrar ahora es
malo aunque el jugador sea bueno. Es el indicador que separa "está barato" de
"sigue cayendo".

**Precio máximo** — la regla es *prima solo a quien sube*:

| Situación | Puja máxima |
|---|---|
| Sube de forma sostenida | valor **+15%** |
| Girando al alza | valor **+10%** |
| Cae, pero frenando | valor **−5%** |
| Cae acelerando | valor **−10%** |
| Probabilidad 0% | **no pujar** |
| Juega pero media < 2,5 pts | **no pujar** |

**Veredictos**: `COMPRAR` · `ESPERAR` (bueno pero cayendo, no pagues prima) ·
`ESPECULATIVO` (sin probabilidad publicada) · `LOTERIA` (≤1 partido jugado,
muestra insuficiente) · `RELLENO` · `NO COMPRAR`.

## Avisos

Los nombres ambiguos se señalan en vez de adivinarse. "Marcos" devuelve los
cinco posibles con su equipo para que concretes.

Las noticias se fechan infiriendo el año: FútbolFantasy solo publica `dd/mm`, y
si esa fecha aún no ha pasado este año, la noticia es del anterior. Sin esto se
cuelan avisos de hace ocho meses como si fueran de ayer.

## Recarga completa

```bash
python scrape.py --full     # historial de puntos de los 660 jugadores (lento)
```

Innecesario para el uso normal: `analiza.py` pide las fichas bajo demanda, solo
de los jugadores que le nombres.

## Conectar tu cuenta

Da acceso a tu mercado real, tu presupuesto y los movimientos de la liga. Se
hace **una vez** y después la sesión se refresca sola.

### Opción 1: email y contraseña (recomendada)

```bash
python laliga_auth.py password
```

Te pide el email y la contraseña por consola. Sin navegador. La contraseña no
se ve al teclear, viaja solo a `login.laliga.es` por HTTPS y **no se guarda en
ningún sitio**.

Usa esta si la página de login del navegador se queda muerta al pulsar el botón:
esa página carga su interfaz desde un CDN externo y depende de unos claims que
la policy solo rellena cuando la abre la app oficial.

### Opción 2: navegador

Necesaria si entras a LaLiga con **Google, Apple o Facebook**, porque entonces
no tienes contraseña propia que darle a la opción 1.

```bash
python laliga_auth.py login      # imprime un enlace
```

Al terminar, el navegador intentará abrir `authredirect://...` y dará error:
**es lo esperado**. No cierres la pestaña — copia la URL completa de la barra de
direcciones y pégala:

```bash
python laliga_auth.py codigo "authredirect://com.lfp.laligafantasy?code=..."
```

### Comprobar

```bash
python laliga_auth.py estado
```

Los tokens se guardan en `data/tokens.json` con permisos `0600`, y esa carpeta
está en `.gitignore`.

## Estado de la liga

```bash
python sync.py            # detecta tu liga y vuelca todo a data/liga.json
python sync.py --resumen  # solo imprime, sin escribir
```

Deja en `data/liga.json`: tu dinero real, el mercado con quién vende cada
jugador, el histórico de movimientos, y cuatro cosas calculadas que la API no
da hechas.

**Saldo estimado de cada rival.** Se reconstruye desde el log de actividad
partiendo de los 100 M iniciales. El log **no registra las recompensas** (bonus
diario, premio de once ideal), así que todos los saldos salen cortos: se mide
el desvío contra tu dinero real —el único que la API publica— y se suma a los
rivales. Quedarse corto es el error que duele cuando valoras quién puede
pagarte una cláusula, así que el número es un **mínimo**, no una estimación
centrada.

**Quién tiene a quién.** El mercado marca qué jugadores los vende un mánager
(`marketPlayerTeam`) y cuáles son libres (`marketPlayerLeague`).

**Prima real pagada.** Compara cada compra del log con el valor de mercado del
jugador. Solo se calcula para los que hoy siguen en el mercado; para el resto
no hay con qué comparar y queda a `null` a propósito.

**Alertas de cláusula.** Tus jugadores sin escudo cuya cláusula esté al alcance
del saldo de algún rival, ordenados por margen sobre el valor: los de margen
bajo son los que te pueden quitar barato.

## Tu plantilla

`informe.py` añade tres cosas más sobre tus propios jugadores.

**Ventas recomendadas.** `VENDER` si está lesionado, si no va a jugar, o si el
valor cae mientras no puntúa. `MANTENER` si sube: vender en plena subida es
regalarla. `ACEPTAR OFERTA` cuando la puja supera la prima habitual de la liga,
aunque el jugador no fuera un descarte.

**Ofertas recibidas.** Las ofertas pendientes van por `playerTeamId` —el hueco
en plantilla, no el id de jugador— porque `/market/{id}/offer` solo acepta POST.
Cada una se compara con el valor y con la prima media de la liga. Si la oferta
queda por debajo del valor se marca: el jugador puede sobrar, pero no a
cualquier precio.

**Clausulazos.** Jugadores de rivales cuya cláusula te cabe en la caja, con
lo que pagas de más sobre su valor y lo que te quedaría después. Los que tienen
la cláusula bloqueada **no se esconden**: se marcan con la fecha en que se
abren, que es lo que hace falta para preparar el golpe. Se descartan los que
llevan escudo, los lesionados y los que no llegan a 3 puntos esperados.

**Once óptimo.** Prueba las doce formaciones que tu liga permite y se queda con
la de más puntos esperados, descartando lesionados y a quien no vaya a jugar.
Cuando FútbolFantasy no publica probabilidad se asume un 70%, el mismo umbral
con el que se considera titular a alguien en el resto del análisis, y la fila
queda marcada.

### Consultas sueltas

```bash
python laliga_api.py ligas
python laliga_api.py mercado LIGA_ID
python laliga_api.py dinero EQUIPO_ID
python laliga_api.py actividad LIGA_ID
```

### Cómo funciona por dentro

Azure AD B2C de LaLiga en `login.laliga.es`, con el `client_id` de la app móvil
(`af88bcff-…`) porque es el único que acepta tanto contraseña como los logins
federados. Dos policies distintas según la opción:

- **Opción 1** — `B2C_1A_ResourceOwnerv2`, flujo ROPC: `grant_type=password`
  contra el endpoint de token. El `scope` tiene que incluir el propio
  `client_id` (`openid <client_id> offline_access`) o B2C emite un token con
  otra audiencia y la API lo rechaza con 401.
- **Opción 2** — `B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN`, authorization code + PKCE.
  El `redirect_uri` es un esquema propio de la app que el navegador de
  escritorio no sabe abrir, pero deja el `code` en la barra de direcciones.

El refresco usa **la misma policy que emitió el token** (se guarda en
`tokens.json`), con las demás combinaciones como red de seguridad.

El access token dura 24 h y el refresh token **rota en cada uso**: hay que
guardar el nuevo cada vez o se pierde la sesión.

Dos endpoints son **públicos, sin token**: `/api/v1/competition/1/players`
(843 jugadores con valor oficial, puntos por jornada y estado físico) y
`/api/v3/teams-master`.

### Por qué siguen haciendo falta los dos orígenes

La API oficial no publica ni la **tendencia de precio** ni la **probabilidad de
alineación**. Eso solo lo tiene FútbolFantasy. La API, a cambio, da el valor
oficial exacto, tu dinero y el feed de la liga. El análisis cruza ambos.

## Por qué el botón no está en la página publicada

La versión publicada como artifact es una **foto fija**: una página en claude.ai
no puede alcanzar tu PC ni tu sesión de LaLiga, así que no hay nada que pueda
actualizar. El botón y el estado solo aparecen cuando la sirve `servidor.py`,
que lo detecta preguntando por `/estado`. Se ocultan solos en vez de ofrecer
algo que no funcionaría.

El artifact sigue siendo útil para consultarlo desde fuera de casa; para datos
en vivo, el servidor local.

## Requisitos

Python 3.9+. Solo librería estándar, sin dependencias que instalar.
