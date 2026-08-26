# VideoGUI

VideoGUI es una aplicación de escritorio para Linux que permite inspeccionar, organizar y convertir las pistas de un vídeo mediante una interfaz gráfica. Utiliza FFmpeg como motor multimedia y Qt 6 para la interfaz.

Está pensada para preparar archivos de vídeo sin tener que escribir órdenes de FFmpeg: permite elegir las pistas que se conservarán, cambiar su orden y descripción, ajustar la imagen, convertir el audio y mantener subtítulos, capítulos y metadatos.

## Funciones principales

- Lectura de vídeos AVI, MP4 y MKV.
- Conversión a MKV, MP4 o AVI.
- Gestión independiente de pistas de vídeo, audio y subtítulos.
- Consulta de información técnica por pista: códec, resolución, FPS y formato de píxel en vídeo; canales, frecuencia y bitrate en audio; y estado forzado en subtítulos.
- Incorporación de pistas procedentes de archivos externos.
- Cambio de orden, título, idioma y disposición predeterminada o forzada de cada pista.
- Copia directa de pistas sin recodificación cuando se desea conservar el contenido original.
- Codificación de vídeo H.264, HEVC, AV1 y VP9.
- Ajuste a resoluciones habituales o a dimensiones personalizadas.
- Conservación o modificación de la relación de aspecto, con recorte, deformación o bordes negros.
- Control mediante calidad constante, bitrate variable o bitrate constante.
- Audio AAC, AC3, MP3, Opus y FLAC, además de copia directa.
- Normalización de volumen y refuerzo de diálogos.
- Aceleración NVIDIA NVENC/CUDA cuando está disponible, con alternativa automática mediante CPU.
- Procesamiento por lotes con validación previa, recuperación de trabajos y seguimiento del archivo actual y del conjunto completo.
- Preajustes reutilizables con filtros de idioma independientes para vídeo, audio y subtítulos.
- Interfaz en español, inglés, francés, italiano y alemán, y varios temas visuales.
- Avisos sonoros en los cuadros de diálogo y confirmación.

## Requisitos

VideoGUI necesita:

- Linux con entorno gráfico.
- Bash 4.2 o posterior.
- Python 3.10 o posterior.
- FFmpeg y FFprobe.
- Bibliotecas gráficas de Qt para OpenGL/EGL, X11/XCB y xkbcommon.
- Espacio libre suficiente para los vídeos convertidos.

El instalador reconoce distribuciones basadas en Debian, Ubuntu, Linux Mint, Fedora, RHEL, Arch Linux, openSUSE y SUSE.

La aceleración por GPU es opcional. Para utilizar NVIDIA, el controlador y la versión instalada de FFmpeg deben proporcionar los codificadores NVENC correspondientes. La aplicación también funciona únicamente con CPU.

La ruta CUDA convierte a `NV12` los vídeos que se escalan en la GPU. Esto permite codificar de forma fiable mediante H.264 NVENC fuentes habituales H.264 o HEVC, incluidas fuentes SDR de 10 bits, aunque la salida de esa ruta queda en 8 bits. La copia directa del vídeo conserva el formato y la profundidad del original. Para material HDR de 10 bits que deba conservarse como tal, utiliza la copia directa o comprueba el resultado con una configuración y un codificador adecuados antes de procesar una colección completa.

## Instalación recomendada

Descarga o descomprime VideoGUI en una carpeta en la que tu usuario tenga permisos de escritura. Abre un terminal dentro de esa carpeta y ejecuta:

```bash
chmod +x bin/setup bin/videogui
./bin/setup --install
```

El instalador realiza las siguientes operaciones:

1. Detecta la distribución de Linux.
2. Comprueba Python, FFmpeg y las bibliotecas necesarias.
3. Solicita permiso antes de instalar paquetes del sistema que falten.
4. Crea un entorno privado de Python en `gui/.venv`.
5. Instala VideoGUI y PySide6 dentro de ese entorno.
6. Comprueba si NVIDIA NVENC está disponible.

Es posible que `sudo` solicite la contraseña de administración para instalar dependencias del sistema.

Para revisar los requisitos sin instalar ni modificar nada:

```bash
./bin/setup --check
```

Para omitir la confirmación previa del instalador de paquetes:

```bash
./bin/setup --install --yes
```

## Instalación manual

Si la distribución no está reconocida, instala con el gestor de paquetes del sistema Python 3.10 o posterior, el módulo `venv`, FFmpeg, FFprobe y las bibliotecas gráficas requeridas por Qt. Después, desde la carpeta de VideoGUI, ejecuta:

```bash
python3 -m venv gui/.venv
gui/.venv/bin/python -m pip install --upgrade pip
gui/.venv/bin/python -m pip install -e .
```

## Iniciar VideoGUI

Después de instalarlo, ejecuta:

```bash
./bin/videogui
```

La aplicación utiliza su entorno privado, por lo que no es necesario activar manualmente ningún entorno virtual.

## Crear un paquete para otro equipo

Para generar un ZIP limpio y transportable de VideoGUI, ejecuta:

```bash
./bin/package
```

Se crea `dist/VideoGUI.zip` sin incluir el entorno virtual, cachés, archivos temporales ni datos internos del repositorio. En el equipo de destino, descomprime el archivo y ejecuta `bin/setup --install` para crear allí el entorno y comprobar sus dependencias.

## Uso básico

### 1. Abrir un vídeo

Pulsa **Abrir vídeo…** en la pestaña **Archivo individual** y selecciona un archivo AVI, MP4 o MKV. VideoGUI analizará el archivo con FFprobe y mostrará por separado sus pistas de vídeo, audio y subtítulos.

Al abrirlo se propone un nombre de salida terminado en `_compressed.mkv`. Tanto el nombre como el directorio de destino se pueden modificar.

### 2. Elegir las pistas

Utiliza las pestañas **Vídeo**, **Audio** y **Subtítulos** para revisar el contenido.

- **Eliminar / recuperar** excluye o vuelve a incluir una pista sin modificar el archivo original.
- **Subir** y **Bajar**, o el arrastre con el ratón, cambian el orden final.
- **Añadir…** incorpora una pista compatible desde otro archivo.
- Los campos de descripción e idioma se guardan como metadatos de la pista de salida.
- Las opciones **Predeterminada** y **Forzada** controlan la disposición de reproducción.

El panel **Información** muestra los datos técnicos de la pista seleccionada. En vídeo incluye resolución, FPS y formato de píxel; en audio, canales, distribución, frecuencia y bitrate; y en subtítulos indica si la pista original estaba marcada como forzada.

El vídeo original nunca se modifica. Todos los cambios se aplican únicamente al nuevo archivo de salida.

### 3. Configurar el vídeo

Para cada pista de vídeo se puede elegir:

- Copiar la pista original sin recodificar.
- Códec H.264, HEVC, AV1 o VP9.
- Resolución original, 4K, 1440p, 1080p, 720p, 480p o personalizada.
- Ajuste dentro de un marco estándar o cálculo automático a partir del ancho.
- Conservación de la relación de aspecto.
- Recorte, deformación o adición de bordes negros.
- Calidad constante CQ/CRF, bitrate variable VBR o bitrate constante CBR.

En calidad constante, un número menor ofrece normalmente más calidad y genera archivos mayores; un número mayor reduce el tamaño a costa de calidad.

La casilla **Usar aceleración hardware si es posible** permite emplear NVIDIA NVENC cuando FFmpeg ofrece el codificador solicitado. Si no está disponible, VideoGUI utiliza automáticamente el codificador de CPU correspondiente. Desmarca la casilla para forzar siempre la CPU.

Cuando el ajuste de imagen puede realizarse completamente con CUDA, tanto la decodificación como el escalado permanecen en la GPU. El escalado CUDA fuerza el formato `NV12` de 8 bits para mantener la compatibilidad con H.264 NVENC, también cuando el origen es HEVC Main 10. Las operaciones que no están disponibles en los filtros CUDA utilizados —por ejemplo, ciertas combinaciones de recorte o bordes— pasan por los filtros de CPU manteniendo NVENC como codificador cuando sea posible.

### 4. Configurar el audio

Cada pista de audio puede copiarse directamente o convertirse a AAC, AC3, MP3, Opus o FLAC.

La lista de formatos de audio incluye **Vorbis (OGG)**. La pista se codifica como Vorbis mediante `libvorbis` en modo de calidad variable VBR; OGG es el contenedor con el que suele distribuirse este códec como audio independiente. En VideoGUI, la pista Vorbis se guarda dentro del contenedor de vídeo elegido, preferiblemente MKV.

La opción **Normalizar y reforzar diálogos** aplica compresión de rango dinámico y normalización de sonoridad. En audio multicanal también realiza una mezcla estéreo adaptada a la distribución de canales. Esta opción se desactiva al seleccionar **Copiar original**, porque una copia directa no puede aplicar filtros.

### 5. Elegir el formato de salida

En **Directorio de salida**, marca **Mismo que origen** para guardar siempre el resultado junto al archivo abierto. Mientras esté marcado, la ruta se actualiza al abrir otro archivo y la edición del directorio y el botón **Examinar** permanecen desactivados. Desmárcalo para elegir otra carpeta.

Selecciona **MKV**, **MP4** o **AVI** en **Formato de salida**. El nombre propuesto utiliza automáticamente la extensión correspondiente; también puedes escribir una extensión válida en el nombre para actualizar el selector. Si no se indica una extensión compatible, VideoGUI utiliza el formato seleccionado.

MKV es la opción más flexible para combinar diferentes códecs, audios y subtítulos. MP4 y AVI admiten menos combinaciones; la aplicación avisa antes de convertir si alguna pista seleccionada no es compatible con el contenedor elegido.

### 6. Convertir

Pulsa **Convertir**. La barra inferior muestra el porcentaje y la velocidad de procesamiento. Durante la conversión, el botón cambia a **Detener**.

Si se detiene el proceso y se confirma la cancelación, el archivo incompleto se elimina. Si ya existe un archivo con el mismo nombre, VideoGUI pide confirmación antes de sobrescribirlo.

## Preajustes (presets)

Los **Preajustes** permiten guardar una configuración para reutilizarla en archivos individuales y en trabajos por lotes. Se administran desde **Aplicación > Preajustes…**, donde se pueden crear, editar, duplicar y borrar.

Cada preajuste guarda:

- La codificación de vídeo: copia directa o códec, resolución, modo de ajuste, relación de aspecto, recorte o bordes y control de calidad o bitrate.
- La conversión de audio y el uso de normalización y refuerzo de diálogos.
- Si se mantienen los subtítulos.
- Los números de pista que pueden procesarse, del 1 al 20 y por separado para vídeo, audio y subtítulos.
- Un filtro de idiomas independiente para las pistas de vídeo, audio y subtítulos.
- Si cada filtro debe conservar también las pistas cuyo idioma no se pueda reconocer.

Los nombres no distinguen entre mayúsculas y minúsculas ni entre variantes con espacios adicionales, por lo que no se pueden crear dos preajustes equivalentes como `Cine` y ` cine `. **Duplicar** crea una copia completa a la que se asigna un nombre nuevo.

En **Archivo individual**, el preajuste seleccionado se aplica a todas las pistas del vídeo abierto y también queda preparado para el siguiente archivo. Si se selecciona antes de abrir el vídeo, se aplica en cuanto termina el análisis. Las pistas externas que se añadan después reciben igualmente sus opciones correspondientes. Si se cambia manualmente una opción o la inclusión de una pista deja de coincidir con el perfil, el selector pasa a **Personalizado / Sin preajuste**.

La numeración se calcula dentro de cada modalidad y conserva el orden original de detección: vídeo 1, vídeo 2, audio 1, audio 2, etc. Las pistas posteriores a la vigésima se excluyen. Los números seleccionados que no existan en un archivo se ignoran. El filtro de idiomas, cuando está activo, se aplica además de la selección numérica. En cada modalidad, **Incluir solo pista predeterminada** desmarca y bloquea la selección numérica; si el archivo no marca ninguna pista de ese tipo como predeterminada, se utiliza la primera.

En **Procesamiento por lotes** es obligatorio disponer de al menos un preajuste. El selector superior determina el perfil de los archivos que se añadan posteriormente; cada fila puede elegir otro distinto. **Aplicar a todos** asigna el preajuste superior a todas las filas y las devuelve al estado pendiente. Los trabajos guardan el nombre del preajuste, no una copia de su contenido: al probar o procesar se utiliza siempre su versión actual. Si el preajuste ha sido borrado, la fila solicita seleccionar otro.

Los preajustes se almacenan en:

```text
~/.config/VideoGUI/presets.json
```

Si está definida la variable `XDG_CONFIG_HOME`, se utiliza `$XDG_CONFIG_HOME/VideoGUI/presets.json`.

## Idiomas de las pistas

VideoGUI utiliza un catálogo configurable para reconocer el idioma de una pista a partir de su código y de su descripción. Se administra desde **Aplicación > Preferencias > Gestionar idiomas de pistas…**.

Para cada idioma se puede indicar:

- Un nombre identificativo que se muestra en la configuración de los preajustes.
- Una o varias cadenas de reconocimiento, escritas en líneas separadas o separadas por comas.
- El alias especial `@empty`, que reconoce pistas sin código ni descripción de idioma.

El reconocimiento no distingue entre mayúsculas y minúsculas, ignora acentos y signos de puntuación, y evita interpretar alias cortos como fragmentos dentro de otras palabras. Cuando coinciden varios criterios, una coincidencia explícita en el código o la descripción tiene prioridad sobre la regla general `@empty`.

Los filtros de idioma se configuran por separado para **Vídeo**, **Audio** y **Subtítulos** dentro de cada preajuste. En cada tipo de pista se puede:

- Desactivar el filtro para conservar todos los idiomas.
- Activarlo y seleccionar exactamente los idiomas que se desean mantener.
- Decidir si se conservan o se excluyen las pistas cuyo idioma no se reconoce.

Al aplicar un preajuste a un archivo individual, la aplicación informa de las pistas no reconocidas y aplica la regla elegida para idiomas desconocidos. En el procesamiento por lotes, **Probar** detecta como error un filtro activo que no conserve ninguna pista de un tipo necesario; si los subtítulos están desactivados en el preajuste, no exige que haya una coincidencia para ellos.

Al borrar un idioma también se elimina su referencia de todos los preajustes que lo utilicen. **Restaurar idiomas** reemplaza, previa confirmación, todo el catálogo personal por la plantilla incluida con VideoGUI y elimina sus personalizaciones.

El catálogo personal se guarda en:

```text
~/.config/VideoGUI/track_languages.json
```

Con `XDG_CONFIG_HOME` definido, se utiliza `$XDG_CONFIG_HOME/VideoGUI/track_languages.json`. La aplicación crea este archivo a partir de la plantilla inicial y no lo sobrescribe en posteriores arranques.

## Procesamiento por lotes

La pestaña **Procesamiento por lotes** convierte varios vídeos consecutivamente. Es necesario crear al menos un preajuste desde **Aplicación > Preajustes…** antes de utilizarla.

El preajuste general se asigna a los archivos que se añadan posteriormente. Cada fila conserva su propia selección y permite cambiarla sin afectar a las demás. **Aplicar a todos** reemplaza el preajuste de todas las filas por el general y las devuelve a estado pendiente. Los archivos pueden seleccionarse en varias operaciones, eliminarse mediante selección múltiple y reordenarse con los botones de flecha. También pueden ordenarse de forma ascendente o descendente pulsando las cabeceras **Archivo origen**, **Preajuste** y **Estado**.

La salida puede guardarse junto a cada archivo original o en una carpeta común, en formato MKV, MP4 o AVI. Los nombres se forman añadiendo `_compressed`; si el destino ya existe o coincide con otra salida del trabajo, se añaden sufijos `_1`, `_2`, etc. sin sobrescribir archivos.

Al seleccionar una sola fila se puede abrir directamente su carpeta de origen o su carpeta de destino. Durante el procesamiento se muestran por separado el progreso y la velocidad del archivo activo, y el porcentaje total junto con el número de archivos completados.

**Probar** analiza todas las filas que no estén completadas, verifica el preajuste, las pistas, los codificadores, el contenedor y la carpeta de salida, y muestra el resultado en la tabla. Los errores se pueden consultar sin detener el procesamiento. **Procesar** repite la validación y convierte secuencialmente las filas válidas; un error no impide continuar con las siguientes.

**Detener** cancela únicamente la conversión activa, elimina su salida incompleta y detiene la cola. Las filas completadas se conservan y no vuelven a convertirse salvo que se seleccionen y se pulse **Poner como Pendiente**. Las filas canceladas vuelven a validarse cuando se pulsa **Probar** o **Procesar**.

**Guardar trabajo…** almacena el orden, los nombres de los preajustes, estados, errores, resultados y todas las opciones de procesamiento en un archivo `.vgbatch.json`. **Cargar trabajo…** reemplaza el trabajo actual y recupera esos datos. Al probar o procesar se utiliza siempre la configuración actual del preajuste indicado en cada fila. Si un preajuste fue eliminado, la fila solicita seleccionar otro.

## Idioma y apariencia

En **Aplicación > Preferencias** se puede seleccionar:

- Idioma español, inglés, francés, italiano o alemán.
- Tema Predeterminado, Azul, Oscuro, Ocre o Rojo.

La selección queda guardada para el siguiente inicio.

Los cuadros de mensaje y confirmación reproducen un aviso sonoro para que la finalización, los errores y las decisiones pendientes también se perciban cuando la ventana no está en primer plano.

## Configuración guardada

VideoGUI conserva automáticamente las preferencias mediante el sistema de configuración de Qt. En Linux, el archivo se guarda normalmente en:

```text
~/.config/VideoGUI/VideoGUI.conf
```

Si la variable de entorno `XDG_CONFIG_HOME` está definida, la ruta utilizada es:

```text
$XDG_CONFIG_HOME/VideoGUI/VideoGUI.conf
```

En ese archivo se almacenan:

- Idioma y tema seleccionados.
- Posición, tamaño y estado maximizado de la ventana.
- Última pestaña utilizada: archivo individual o procesamiento por lotes.
- Último directorio de salida.
- Último formato de salida seleccionado.
- Preferencia de aceleración por hardware.
- Últimos ajustes de códec, resolución, proporción, calidad y bitrate de vídeo.
- Último formato de audio y estado de normalización.
- Nombre del último preajuste seleccionado.

Los datos completos de los preajustes y el catálogo personal de idiomas se guardan por separado en los archivos indicados en sus respectivos apartados.

Estas preferencias se aplican a los vídeos que se abran posteriormente. El botón **Valores predeterminados** restaura el perfil inicial de codificación.

Los archivos convertidos se guardan en el directorio de salida elegido en la ventana principal. VideoGUI no mueve ni reemplaza el archivo original.

## Rutas utilizadas por la instalación

VideoGUI mantiene sus componentes dentro de la carpeta donde se descomprimió:

```text
VideoGUI/
├── bin/videogui       Lanzador de la aplicación
├── bin/setup          Instalador y comprobador de dependencias
├── bin/package        Generador del paquete ZIP transportable
├── gui/.venv/         Entorno privado de Python y PySide6
└── gui/               Aplicación, idiomas, icono y temas
```

El entorno `gui/.venv` no contiene preferencias personales ni vídeos. Puede reconstruirse ejecutando de nuevo `./bin/setup --install`.

## Solución de problemas

### La aplicación indica que falta FFprobe

Instala FFmpeg desde los repositorios de tu distribución. FFprobe suele incluirse en el mismo paquete. Después comprueba la instalación:

```bash
ffmpeg -version
ffprobe -version
```

### El lanzador no encuentra el entorno virtual

Ejecuta de nuevo la instalación desde la carpeta del programa:

```bash
./bin/setup --install
```

### La aceleración NVIDIA no está disponible

Comprueba los codificadores detectados por FFmpeg:

```bash
ffmpeg -hide_banner -encoders | grep nvenc
```

Si no aparece el codificador necesario, actualiza el controlador NVIDIA o instala una compilación de FFmpeg compatible con NVENC. Mientras tanto, desactiva la aceleración hardware para utilizar la CPU.

### Un vídeo de 10 bits falla o cambia de aspecto al usar NVIDIA

En la ruta de escalado CUDA, VideoGUI convierte la imagen a `NV12` de 8 bits para que H.264 NVENC acepte también fuentes HEVC Main 10. Si aun así falla, comprueba que la GPU pueda decodificar el códec de origen y que el controlador sea compatible con la versión de FFmpeg instalada. Puedes desactivar la aceleración para usar los filtros y codificadores de CPU.

Esta conversión es apropiada para contenido SDR habitual. En material HDR puede modificar el color porque no realiza por sí sola un mapeo HDR a SDR. Si necesitas preservar HDR o los 10 bits, copia la pista de vídeo sin recodificar o utiliza una configuración externa específica y verifica el resultado.

### MP4 o AVI rechazan alguna pista

Selecciona MKV como formato de salida, copia o convierte la pista a un códec compatible, o excluye esa pista antes de convertir.

### Restablecer por completo la configuración

Cierra VideoGUI y cambia de nombre o elimina el archivo de preferencias:

```text
~/.config/VideoGUI/VideoGUI.conf
```

Al iniciar de nuevo, VideoGUI creará una configuración con los valores predeterminados.
