# Panel siempre disponible, con el PC apagado

GitHub ejecuta el pipeline cada 15 minutos en sus servidores y publica la
página. Tu ordenador no pinta nada: puede estar apagado.

El repositorio local ya está creado y con el primer commit hecho. Faltan cinco
pasos, todos en la web de GitHub.

## 1. Crea el repositorio

En [github.com/new](https://github.com/new):

- Nombre: `fantasy` (o el que quieras)
- Visibilidad: **Public**
- **No** marques nada de "Initialize with README"

Tiene que ser público. En las cuentas gratuitas, GitHub Pages solo funciona
desde repos públicos, y los minutos de Actions solo son ilimitados en repos
públicos. Lo que se publica está protegido por la ruta secreta del paso 3.

## 2. Súbelo

Desde `fantasy/`, cambiando `TU-USUARIO`:

```bash
git remote add origin https://github.com/TU-USUARIO/fantasy.git
git push -u origin main
```

Tus datos no viajan: `data/` está en `.gitignore`, así que ni el token ni la
plantilla ni el dinero salen de tu disco. Solo sube el código.

## 3. Añade los tres secretos

En **Settings → Secrets and variables → Actions → New repository secret**:

| Nombre | Valor |
|---|---|
| `LALIGA_EMAIL` | tu email de LaLiga Fantasy |
| `LALIGA_PASSWORD` | tu contraseña de LaLiga Fantasy |
| `RUTA_SECRETA` | una cadena larga al azar, p. ej. `k7f2p9x4m1q8` |

`RUTA_SECRETA` es la carpeta donde se publica el panel. Al ser un secreto, no
aparece en el repositorio aunque sea público: nadie puede deducir la URL
leyendo el código.

Genera una así:

```bash
python -c "import secrets; print(secrets.token_hex(8))"
```

## 4. Activa Pages

En **Settings → Pages → Build and deployment → Source**, elige
**GitHub Actions**. No toques nada más.

## 5. Lánzalo una vez a mano

En **Actions → Actualizar panel → Run workflow**. Tarda un par de minutos.

Cuando acabe en verde, tu panel está en:

```
https://TU-USUARIO.github.io/fantasy/TU-RUTA-SECRETA/
```

Ábrela en el iPhone y añádela a la pantalla de inicio.

## Qué tener en cuenta

**No es una contraseña.** Cualquiera con esa URL ve tu panel. La ruta es
imposible de adivinar y la página lleva `noindex`, así que no la encontrará un
buscador, pero si compartes el enlace, compartes los datos.

**El cron se retrasa.** GitHub no garantiza la puntualidad de los `schedule`:
cuando hay carga puede pasar de 15 a 20 minutos. Para el mercado de fantasy da
igual, pero que no te extrañe.

**Se apaga solo a los 60 días.** GitHub desactiva los workflows programados en
repos sin actividad durante dos meses. Te avisa por correo y se reactiva con un
clic.

**Tu contraseña está en GitHub.** Cifrada, en tu propia cuenta, y no aparece en
los logs. Aun así es tu contraseña en un tercero: si no te convence, borra los
secretos y quédate con el servidor local.

## Si algo falla

En **Actions** verás la ejecución en rojo. El paso que suele fallar es el
primero, *Iniciar sesión en LaLiga*: casi siempre es que el email o la
contraseña no son correctos, o que tu cuenta entra con Google/Apple/Facebook y
no tiene contraseña propia. En ese caso créala desde la app de LaLiga.
