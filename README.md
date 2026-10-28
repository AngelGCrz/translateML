# translateML

Genera el `info.json` de cada idioma de un juego **PixiJS** a partir de su plantilla inglesa
y de la hoja `Multidioma.xlsx` donde Data mantiene las traducciones.

- Solo cambia los textos traducibles. Estructura, orden, números, colores, offsets, imágenes y
  formato del archivo quedan exactamente como en la plantilla.
- No reparte textos entre páginas ni crea elementos: la distribución visual es la de la plantilla.
  La única excepción son las frases que la plantilla corta en varias líneas: la traducción completa
  va en la primera línea y las de continuación se quitan (sección 3).
- Funciona sin Internet ni credenciales: la hoja se descarga a mano desde Google Sheets.
- Admite 18 idiomas, configurables (`config/languages.json`).

Versión 1.0.0. Python 3.9 o superior, macOS, Linux o Windows.

---

## 1. Instalación (una vez por equipo)

Copia o clona la carpeta `translateML` y ejecuta, con Internet:

| Sistema | Instalar | Ejecutar |
|---|---|---|
| macOS / Linux | `./setup.sh` | `./translateml.sh …` |
| Windows (CMD) | `setup.cmd` | `translateml.cmd …` |

`setup` crea el entorno `.venv` e instala el programa y su única dependencia, `openpyxl` (lee los
`.xlsx`). Si `python3` no es la versión correcta: `PYTHON=python3.12 ./setup.sh`.
No copies `.venv` entre equipos ni entre sistemas: vuelve a ejecutar `setup`.

Comprobación:

```bash
./translateml.sh --version
./translateml.sh verify tests/fixtures/pixi/*/info.json
```

> Los ejemplos usan `./translateml.sh`; en Windows usa `translateml.cmd` con las mismas opciones.
> Con el entorno activado también existe el comando `translateml`.

## 2. Uso rápido: un comando

1. Descarga la hoja desde Google Sheets: **Archivo > Descargar > Microsoft Excel (.xlsx)**,
   cuando todas las fórmulas hayan terminado de calcularse.
2. Genera todos los idiomas a partir de la plantilla inglesa del juego:

```bash
./translateml.sh generate ../pixi/g490/public/assets/languages/eng/info/info.json --xlsx ~/Downloads/Multidioma.xlsx
```

`generate` extrae los textos de la plantilla y genera cada idioma habilitado en
`output/<juego>/<carpeta>/info.json`. El nombre del juego (`g490`) se toma de la ruta (`--name`
para otro). `--lang esp,deu` genera solo esos idiomas.

3. Revisa el estado al final de la salida y el informe `output/<juego>/xlsx-build-report.json`:

| Estado | Significado | Código de salida |
|---|---|---|
| `ok` | Todo traducido y sin avisos | 0 |
| `warnings` | Generado; algunos textos se quedan en inglés o hay algo que revisar | 0 |
| `error` | Al menos un idioma **no** se generó (pestaña ausente, asociación ambigua…) | 1 |

4. Copia cada `output/<juego>/<carpeta>/info.json` a la carpeta de **ese mismo idioma** en el juego,
   por ejemplo `output/g490/esp/info.json` → `pixi/g490/public/assets/languages/esp/info/info.json`.
   `eng/info.json` es idéntico a la plantilla: no hace falta copiarlo. **Nunca copies otro idioma
   sobre la plantilla inglesa**: es la fuente de todo el proceso.

## 3. La hoja Multidioma.xlsx

`translateML` lee el archivo **sin modificarlo** y no actualiza la hoja de Google. La forma de la hoja
se describe en `config/sheets.json`. La configuración actual corresponde a la hoja real de Data:

```json
{ "header_row": 0, "association": "text", "text_column": "C", "positional_fallback": false }
```

- Sin fila de cabeceras; numeración en la columna B (se ignora) y texto en la columna **C**.
- Una pestaña por idioma: `ENG` (origen), `ESP`, `DEU`, `ELL`, … `ZH-HANT` (ver `config/languages.json`).
- **ENG**: los textos en inglés, frase a frase, con rótulos de sección si se quiere (`PAYTABLE`).
- **Resto de pestañas**: una fórmula por fila que apunta a ENG, como hoy
  (`=GOOGLETRANSLATE(ENG!C7,"en","es")`), o una traducción revisada a mano en esa celda.

### Cómo se relaciona la hoja con la plantilla

1. **Cada fila de ENG con su texto en la plantilla, por texto inglés exacto** (`association: "text"`).
   Se compara con el texto sin viñeta ni sangría (como aparece en `output/<juego>/extracted.csv`) y
   sin tener en cuenta los espacios al principio y al final de la celda.
   - Un texto repetido en la plantilla (`GAME RULES` en dos páginas) recibe la misma traducción en
     todas sus ubicaciones.
   - Una fila que no coincide exactamente **no se usa** y se informa. Nunca se busca un parecido.
   - **Frases que en la plantilla ocupan varias líneas:** Data las escribe enteras en una celda,
     como cualquier otra. El programa sabe a qué líneas corresponden (ver abajo).
2. **Cada traducción con su fila de ENG, por la referencia de su fórmula** (`ENG!C7` → fila 7),
   también en rangos (`ENG!C2:C`) y en la forma en que Google exporta sus funciones
   (`__xludf.DUMMYFUNCTION("GOOGLETRANSLATE(ENG!C7,…)")`).
   Una celda sin fórmula hacia ENG (por ejemplo un rótulo copiado) no se usa, salvo que se active
   `positional_fallback` (misma fila que en ENG). Está desactivado: no se adivina por posición.

Se leen los **valores guardados** en el `.xlsx`, nunca el texto de las fórmulas. `openpyxl` no calcula
fórmulas: si una pestaña no tiene ningún valor guardado, el idioma no se genera y se pide volver a
descargar el archivo.

### Frases de varias líneas

En la plantilla algunas frases están cortadas en dos líneas para que quepan:

```text
"• All symbols pay when they appear consecutively left to right, from reel 1, except scattered",
"   ##sym_13.png## which pays on any position. ",
```

En la hoja, Data escribe la frase completa en **una celda**, sin preocuparse de los cortes:
`All symbols pay when they appear consecutively left to right, from reel 1, except scattered ##sym_13.png## which pays on any position.`
El programa reconoce que esa frase son esas líneas (las une con un espacio y compara exactamente) y:

- **Por defecto**, pone la traducción completa en la primera línea, con su viñeta, y **quita las
  líneas de continuación** de la lista:

  ```text
  "• Todos los símbolos pagan … excepto el símbolo disperso ##sym_13.png## que paga en cualquier posición. ",
  ```

- Si la traducción tiene **los mismos saltos de línea** que la plantilla (opcional, por si alguien
  quiere decidir dónde se corta), cada trozo va a su línea y no se quita ninguna.

Detalles:
- La validación comprueba que solo desaparecen esas líneas y que todo lo demás queda idéntico.
  El informe las lista en `merged_lines`.
- Los marcadores se comprueban sobre la frase completa. Si la traducción pierde uno, toda la frase
  se queda en inglés y no se quita nada.
- Una línea larga puede no caber en la página: revísalo en el juego. El programa nunca corta por longitud.
- Si una línea de esa frase también tiene su propia fila en la hoja, se usa esa fila y la frase no se
  une (`sentence_overlaps_rows`), para que una línea nunca reciba dos traducciones distintas.

### Qué se conserva en inglés (y se informa)

- **Inglés distinto** entre hoja y plantilla (`not_in_template`), incluidas erratas o marcadores con
  otro nombre (`##jackpot_grand.png##` frente a `##text_grand.png##`). Corrige la hoja o la plantilla.
- **Textos de la plantilla que no están en la hoja** (lista `missing` del informe).
- **Traducciones que pierden, duplican o alteran un marcador** (`token_mismatch`), como
  `## sym_11.png ##` en lugar de `##sym_11.png##`.

Nunca se escribe `null`, una cadena vacía ni un texto inventado en lugar de una traducción.

### Formato alternativo con claves (`association: "key"`)

Una fila por línea del JSON, con una columna `KEY` generada por el programa (Data no la escribe):

```bash
./translateml.sh xlsx export output/g490/manifest.json            # eng-sheet.csv: KEY, TEXT
./translateml.sh xlsx export output/g490/manifest.json --xlsx F   # además eng-new-rows.csv con lo que falta
```

En las demás pestañas, `=ENG!A2` copia la clave y `=GOOGLETRANSLATE(ENG!B2,"en","es")` el texto.
Requiere `"association": "key"` y `"header_row": 1`. Con este formato las frases de varias líneas se
traducen línea a línea. No es el formato que usa Data hoy.

## 4. El informe `xlsx-build-report.json`

Por idioma: `status`, `output`, `applied` (traducciones aplicadas), `missing` (claves que se quedan en
inglés), `marker_issues`, `same_as_english` y `problems`. Además: textos extraídos (`extracted_texts`),
cadenas pendientes de revisión en la plantilla (`pending_review`) y problemas de ENG (`eng_problems`).

| Tipo | Gravedad | Qué hacer |
|---|---|---|
| `duplicate_key`, `invalid_key`, `ambiguous` | **Error**: el idioma no se genera | Mismo inglés con traducciones distintas o claves repetidas: corregir la hoja |
| `no_cached_value` | **Error** | Volver a descargar el `.xlsx` cuando las fórmulas estén calculadas |
| pestaña o cabecera ausente o repetida | **Error** | Revisar la hoja o `config/languages.json` / `config/sheets.json` |
| `sentence_overlaps_rows` | Aviso | Frase de varias líneas cuya primera línea también tiene fila propia: se usa esa fila |
| `not_in_template` | Aviso | Fila de ENG sin texto idéntico en la plantilla |
| `eng_out_of_sync`, `not_in_sheet` | Aviso | Texto de la plantilla sin fila (o con otro inglés) en la hoja |
| `token_mismatch` | Aviso | La traducción perdió o alteró un marcador: queda en inglés |
| `newline_count` | Aviso | La traducción tiene otro número de saltos de línea |
| `same_as_english` | Aviso | Traducción idéntica al inglés (por ejemplo, Google no la tradujo) |
| `formula_error`, `empty_formula_result`, `whitespace_only` | Aviso | Celda con `#N/A`/`Loading...`, vacía o solo con espacios |
| `unlinked` | Aviso | Celda sin fórmula hacia ENG: no se usa |

Otros archivos de `output/<juego>/`: `manifest.json` (claves internas → rutas del JSON; no se edita),
`extracted.csv` (los textos extraídos), `extraction-report.json` (reglas y auditoría),
`key-changes.json` (cambios de claves entre extracciones) y `sheets/<idioma>.csv` (las traducciones
aplicadas y la columna `MERGED` con las líneas unidas, reutilizables con `rebuild --texts`).

## 5. Comandos

| Comando | Qué hace |
|---|---|
| `generate PLANTILLA --xlsx F [--lang …] [--name …] [--out …]` | `extract` + `xlsx build` en un paso |
| `extract PLANTILLA` | Extrae textos y rutas a `output/<juego>/` y conserva las claves anteriores |
| `xlsx build MANIFEST --xlsx F [--lang …]` | Genera los idiomas desde el `.xlsx` |
| `xlsx inspect --xlsx F` | Describe pestañas, columnas y fórmulas del archivo (solo lectura) |
| `xlsx languages --xlsx F` | Lista los 18 idiomas y si su pestaña existe; sugiere nombres parecidos |
| `xlsx export MANIFEST [--xlsx F]` | Filas `KEY`/`TEXT` para el formato con claves |
| `analyze PLANTILLA` | Qué se traduciría y qué queda pendiente de revisión, sin escribir nada |
| `verify PLANTILLA …` | Comprueba que extraer y reconstruir el inglés da el archivo idéntico |
| `rebuild MANIFEST [--texts CSV] [--lang …]` | Reconstruye un idioma desde un CSV `KEY`,`TEXT` |

Los comandos `xlsx` aceptan `--sheets-config RUTA` (antes del subcomando) para usar otra
configuración de hoja, por ejemplo una por juego: `xlsx --sheets-config g500.json build …`.
`generate` la acepta directamente.

## 6. Configuración (`config/`)

| Archivo | Contenido |
|---|---|
| `settings.json` | Carpeta de salida (`output_root`), nombre del archivo (`info.json`), política de traducciones faltantes (`keep_source` o `error`), nombres de columna `KEY`/`TEXT` |
| `sheets.json` | Forma de la hoja: `header_row` (0 = sin cabeceras), `association` (`text`/`key`), `text_column` (letra), `positional_fallback`, `xlsx_file` por defecto y ajustes por pestaña en `tabs` |
| `languages.json` | Idioma de origen y los 18 idiomas: `code` (interno), `tab` (pestaña), `folder` (salida), `enabled` |
| `profiles/pixi_info.json` | Qué partes de la plantilla son texto traducible (sección 7) |

### Idiomas

Los 18 idiomas de los juegos están habilitados: `eng`, `esp`, `deu`, `ell`, `fra`, `ido`, `ita`, `jpn`,
`kmb`, `krs`, `mly`, `por`, `rus`, `tha`, `tur`, `vie`, `zh-hans`, `zh-hant`. Código, pestaña y carpeta
son independientes: por ejemplo, `"tab": "Español (revisado)", "folder": "es-ES"` es válido.

Para añadir o recuperar un idioma: Data crea su pestaña (igual que ESP), se descarga el archivo,
`xlsx languages` confirma que aparece y se pone `"enabled": true`. Para excluir uno temporalmente,
`"enabled": false` o `--lang` con la lista deseada.

Al cargar se valida: códigos, pestañas (sin distinguir mayúsculas) y carpetas sin repetir; que la
carpeta sea un nombre simple (nunca una ruta); que todo idioma habilitado tenga pestaña; y que el
idioma de origen esté habilitado.

## 7. Qué se considera texto traducible

El motor recorre cualquier `info.json`; lo específico de PixiJS está en `config/profiles/pixi_info.json`:

- `include`: dónde buscar, si existe en la plantilla — `rules.pages[*]` (recursivo),
  `payTables[*].titles[*].text`, `payLines[*].titles[*].text`. Una ruta ausente se informa y no se crea.
- `text_keys`: dentro de una sección recursiva solo se traduce lo que está bajo `text` o `lines`.
  Cualquier otra cadena va a la **auditoría** (`analyze`, `extraction-report.json`) para revisar.
- `technical_keys` / `technical_values`: nunca se traducen `color`, `size`, `offset`, `stroke`,
  `align`, `path`, `src`, `fontName`, `scale`, `tag`…, ni valores como `rgb(...)`, `0,294`,
  `sym_2.png`, `info1_png` o `res.info_pages`.
- `protected_prefix` / `protected_suffix` / `protected_tokens`: la viñeta `• `, las sangrías, los
  espacios finales y `{fixedJackpot}` se separan del texto y se restauran; los marcadores `##…##`
  quedan en el texto y se comprueba que la traducción los conserve exactamente.

Para un juego con otra estructura, ejecuta `analyze` sobre su plantilla. Si la auditoría muestra
textos visibles fuera de las reglas, añade su ruta a `include` (o su clave a `text_keys`) en el perfil.
No hace falta tocar el código.

### Claves internas

Cada texto recibe una clave (`T0001`…) que guarda su ruta en `manifest.json`. Al volver a extraer,
las claves se conservan: una línea insertada no desplaza las siguientes, un texto editado mantiene la
suya y las claves de textos eliminados no se reutilizan (`key-changes.json`). `extract --fresh-keys`
vuelve a numerar. Data nunca ve ni gestiona estas claves en el formato por texto.

## 8. Garantías

- La plantilla y el `.xlsx` no se modifican nunca; todo se escribe en `output/`.
- Cada `info.json` generado se valida antes de escribirse: mismo JSON salvo los textos traducidos,
  mismas propiedades en el mismo orden, mismos números, booleanos y `null`.
- Se sustituyen solo los literales de texto dentro del archivo original, así que el formato
  (indentación, espacios, orden) se conserva byte a byte. `eng/info.json` es idéntico a la plantilla.
- Los textos en japonés, coreano, chino, tailandés, ruso o griego se escriben tal cual (UTF-8, sin `\u`).

Qué **no** comprueba: si la fuente del juego tiene esos caracteres, ni si un texto cabe en su página.
Eso se revisa en el juego (por ejemplo, el jemer usa espacios invisibles `​`).

## 9. Problemas frecuentes

| Mensaje | Causa y solución |
|---|---|
| `Falta el entorno .venv` | Ejecuta `setup.sh` / `setup.cmd` |
| `La plantilla cambió desde la extracción` | Vuelve a ejecutar `generate` (o `extract`). Si la plantilla inglesa contiene otro idioma, restáurala primero |
| `no tiene la pestaña 'ITA' … ¿Es 'Ita'?` | Corrige `tab` en `languages.json` o el nombre de la pestaña |
| `no tiene la columna 'TEXT'` | Revisa `header_row`/`text_column` en `sheets.json` (`xlsx inspect` muestra la forma real) |
| `ninguna de las N fórmulas … tiene valor guardado` | Descarga de nuevo el `.xlsx` desde Google Sheets cuando haya terminado de calcular |
| Una frase larga se sale de la página en el juego | Es una frase unida en una línea; acórtala en la hoja o ajusta la plantilla |
| `not_in_template` en una fila que parece igual | Hay una diferencia mínima (espacio junto a `##…##`, coma, errata): compara con `extracted.csv` |

## 10. Para desarrolladores

### Estructura

| Módulo | Responsabilidad |
|---|---|
| `translateml/template.py` | Carga y valida la plantilla; posición de cada literal de texto; escritura que solo cambia esos literales |
| `translateml/jsonpath.py` | Rutas (`rules.pages[0].items.lines[3]`), selectores con `*` y recorrido |
| `translateml/extraction/` | Perfiles (`rules.py`), clasificación técnica/texto y elementos protegidos (`segments.py`), motor y auditoría (`extractor.py`) |
| `translateml/keys.py` | Conservación de claves entre extracciones (alineación ordenada) |
| `translateml/rebuild.py` | Inserta los textos, restaura prefijos/sufijos y valida marcadores |
| `translateml/validation.py` | Compara el JSON generado con la plantilla |
| `translateml/export.py` | Manifest, CSV e informes |
| `translateml/pipeline.py` | Pasos compartidos: cargar manifest y generar un idioma |
| `translateml/config.py` | `settings.json` y `languages.json` |
| `translateml/sheets/` | Lectura del `.xlsx` (`xlsx.py`), tabla y fórmulas (`table.py`), asociación (`association.py`), inspección y comandos `xlsx` |
| `translateml/cli.py` | Línea de comandos |

La extracción y la reconstrucción usan solo la biblioteca estándar; `openpyxl` solo se importa al leer un `.xlsx`.

### Pruebas

```bash
.venv/bin/python -B -m unittest discover -s tests -t .
```

- Fixtures reales: las plantillas g402, g475, g490 y g500 (`tests/fixtures/pixi`).
- Los `.xlsx` de prueba se crean con fórmulas y valores guardados como los exporta Google Sheets
  (`tests/xlsx_builder.py`). Sin `openpyxl` esas pruebas se omiten.
- Las pruebas usan su propia configuración (`tests/fixtures/`), no la del proyecto.
- Prueba de integración con el archivo real, opcional:
  `TRANSLATEML_REAL_XLSX=~/Downloads/Multidioma.xlsx .venv/bin/python -B -m unittest tests.test_xlsx.RealXlsxTest`

### Distribuir

La carpeta del proyecto es la distribución: `config/`, `translateml/`, `tests/`, `pyproject.toml`,
`requirements.txt`, `setup.*` y `translateml.*`. No incluyas `.venv/`, `output/` ni archivos `.xlsx`
(ya están en `.gitignore`). La instalación es editable (`pip install -e .`), por lo que el programa
usa la carpeta `config/` del proyecto.

### Limitaciones conocidas

- Las frases que la plantilla corta en varias líneas se traducen en una sola línea; si no cabe, hay que ajustarlo en el juego.
- Sin interfaz gráfica: el flujo completo se hace con un comando.
- Los scripts de Windows (`setup.cmd`, `translateml.cmd`) no se han probado todavía en un equipo Windows.
