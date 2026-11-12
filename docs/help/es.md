<!-- Kalmido help, Spanish (2.1072.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the interface shows it.
Check: python3 tools/check_userhelp.py. -->

<!-- help: files#how-to-set-up-a-scan-inbox src=64eddd039b -->
## Configurar una bandeja de escaneo

Una bandeja de escaneo envía los escaneos nuevos de una carpeta de tu ordenador directamente a tus documentos.

1. Abre **Ajustes** > **Integraciones** y busca **Documentos: entradas**.
2. En **Vigilante de carpetas**, descarga el programa para tu ordenador (Mac o Windows).
3. Abre **Nueva bandeja de escaneo**, escribe un **Nombre**, elige la carpeta en **En la carpeta** y pulsa **Crear bandeja**.
4. Kalmido muestra el **Código de configuración** solo esta vez. Pulsa **Copiar**, inicia el programa, pega el código y elige
   la carpeta que quieres vigilar.

Qué pasa después: cada archivo nuevo de esa carpeta se sube, se lee y se ordena en tus documentos. Encuentras la bandeja en el
mismo lugar para cambiar la carpeta, prolongarla un año o revocarla. Solo tú creas una bandeja de escaneo, nunca un agente.

<!-- help: files#how-to-add-documents-and-find-them-again src=75bd3485cd -->
## Añadir documentos y volver a encontrarlos

1. Abre **Archivos** > **Documentos**.
2. Pulsa **Añadir documentos** y elige PDF o fotos, o arrástralos a la página. En el móvil, **Escanear** fotografía una carta.
3. Escribe una palabra en **Buscar en los documentos…**; la búsqueda también encuentra palabras dentro de las cartas.

Qué pasa después: Kalmido lee cada documento y rellena fecha, importe y remitente. Lo que no tiene claro espera en
**Por revisar**: ábrelo, corrige lo que falle y pulsa **Revisado** (o **Aceptar todo** para las sugerencias).

<!-- help: files#how-to-share-a-folder src=2b0b00ac10 -->
## Compartir una carpeta

1. Abre **Archivos** y el menú **Más** (⋯) de la carpeta, luego **Compartir…**.
2. En **Compartir con…** elige una persona, un grupo o un agente.
3. Elige **Puede ver** o **Puede editar**, pulsa **Añadir** y luego **Listo**.

Qué pasa después: la persona ve la carpeta y todo lo que contiene, también lo que se añada más tarde. Solo el propietario
puede compartir una carpeta.

<!-- help: agent-setup#how-to-create-your-personal-agent src=c5dbd2659a -->
## Crear tu agente personal

Un agente es un asistente (por ejemplo Claude) que trabaja en Kalmido con su propia cuenta y solo ve lo que compartes con él.

1. Abre **Ajustes** > **Agentes** y la pestaña **Configurar**.
2. En **Tus agentes personales** rellena **Nombre visible** y los otros dos campos y pulsa **Crear agente**.
3. En la ventana que se abre, elige tu **Ordenador** y la **Carpeta del proyecto** y pulsa **Crear comando**.
4. Pulsa **Copiar**, abre la terminal en ese ordenador, pega el comando y pulsa Intro. Luego **Listo**.

Qué pasa después: el agente aparece en **Tus agentes personales**. Todavía no ve nada: dale un proyecto o una carpeta. El
comando sirve una vez y solo unos minutos; **Configurar** en la fila del agente crea uno nuevo.

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=2e7c802506 -->
## Dar a un agente acceso a un proyecto o una carpeta

Un proyecto:

1. Abre el menú (⋯) del proyecto y elige **Agente…**.
2. En **Agentes** elige el agente y confirma con **Compartir**.

Una carpeta en Archivos o Conocimiento:

1. Abre el menú (⋯) de la carpeta y elige **Compartir…**.
2. En **Compartir con…** elige el agente, **Puede ver** o **Puede editar**, pulsa **Añadir** y luego **Listo**.

Qué pasa después: el agente trabaja en ese proyecto o carpeta, y solo allí. Cada acceso de un agente queda en el historial;
una carpeta bloqueada nunca se comparte con un agente.

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=c440cd682e -->
## Aprobar lo que pide un agente

1. Cuando un agente necesita tu sí, aparece una tarjeta "… te espera" (en Hoy y en Agentes).
2. Pulsa **Aprobar** o **Rechazar**. Para una propuesta, primero **Revisar la propuesta**.

Qué pasa después: el agente sigue con lo que aprobaste; un paso rechazado no ocurre.

<!-- help: office#how-to-write-a-quotation src=8abb747cdd -->
## Escribir un presupuesto

1. Abre **Oficina** > **Presupuestos** y pulsa **Nuevo presupuesto**. El borrador se abre enseguida.
2. Elige el **Cliente**.
3. Añade líneas con **Añadir servicio**.
4. Cuando esté listo, pulsa **Cerrar**. Después, número, líneas e importes ya no cambian.
5. Pulsa **Enviar** para mandarlo por correo, o **Descargar PDF**.

Qué pasa después: el presupuesto está en la lista. Márcalo como enviado y luego como **Aceptado** o rechazado; de un
presupuesto aceptado sale la factura en un paso. Un borrador se ve con **Vista previa**.

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=b1c09e308f -->
## Convertir un presupuesto en factura

1. Abre el presupuesto aceptado y pulsa **Crear factura**.
2. Elige el **Tipo de factura** y confirma.
3. Revisa la factura, pulsa **Cerrar** y luego **Enviar**.

Una factura sin presupuesto: **Oficina** > **Facturas** > **Nueva factura**.

Qué pasa después: la factura recibe su número al cerrarla, sin huecos. Sigue abierta hasta que se registra un pago.

<!-- help: office#how-to-record-a-payment src=c83bb01e09 -->
## Registrar un pago

1. Abre la factura cerrada y pulsa **Registrar pago**.
2. Revisa fecha e importe y pulsa **Registrar**.

O con el extracto: **Oficina** > **Banco** > **Importar extracto bancario** y acepta la sugerencia con **Asumir**.

Qué pasa después: la factura figura como pagada (o pagada en parte). Solo un administrador de la organización registra pagos.

<!-- help: tasks#how-to-add-a-task-with-a-date src=c89121e185 -->
## Añadir una tarea con fecha

1. Pulsa en **Añadir tarea…** al pie del proyecto (en el móvil: el botón +).
2. Escribe la tarea como la piensas, por ejemplo "Llamar al dentista mañana 15h", o elige la fecha.
3. Pulsa Intro.

Qué pasa después: la tarea queda en el proyecto abierto (o en la **Cesta**) con su fecha y aparece ese día en **Hoy**. Para
cambiar la fecha, abre la tarea y pulsa su fecha: **Hoy**, **Mañana**, **Próxima semana** o un día del calendario.

<!-- help: tasks#how-to-make-a-task-repeat src=7fb71b25d1 -->
## Repetir una tarea

Una tarea recurrente vuelve sola: cada día, cada semana o según tu propia regla.

1. Abre la tarea y pulsa su fecha.
2. Elige en **Repetición**, por ejemplo **Diariamente**, o **Personalizado…** para tu propia regla.
3. Pulsa **Listo**.

Qué pasa después: al completar la tarea aparece la siguiente con la próxima fecha.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=26bbda819e -->
## Asignar una tarea o compartir un proyecto

1. Compartir el proyecto: su menú (⋯) > **Compartir…**, elige la persona en **Compartir con…**, un rol (por ejemplo
   **Miembro**) y pulsa **Añadir**.
2. Asignar una tarea: abre la tarea, pulsa **Asignar** y elige la persona.

Qué pasa después: la persona ve el proyecto y recibe la tarea. Solo se puede asignar a personas del proyecto.

<!-- help: calendar#how-to-create-an-event src=a00f1c721d -->
## Crear un evento

1. Abre **Calendario** y pulsa **Evento** (en el móvil: el botón +).
2. Rellena **Título**, **Empieza** y **Termina** y, si hace falta, **Repetición**.
3. Pulsa **Guardar**.

Qué pasa después: el evento está en el calendario y en tu móvil, si está conectado.

<!-- help: calendar#how-to-subscribe-to-another-calendar src=a8d8302f42 -->
## Suscribirse a otro calendario

1. Abre **Calendario** > **Calendarios** > **Suscripciones…** (o **Ajustes** > **Integraciones** > **Calendarios**).
2. Pulsa **Añadir calendario**.
3. Pega el enlace del calendario y pulsa **Añadir**. Para una cuenta elige **Cuenta CalDAV** y **Buscar calendarios**.

Qué pasa después: sus eventos aparecen en tu calendario, solo para leer y solo para ti.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=e055eae2f6 -->
## Ver Kalmido en el móvil

1. Abre **Calendario** > **Calendarios** > **En el móvil…** (o **Ajustes** > **Integraciones** > **Apps de calendario (CalDAV)**).
2. Pulsa **Nueva contraseña de aplicación** y copia servidor, usuario y contraseña en los ajustes de calendario del móvil.

Qué pasa después: tus eventos y tareas con fecha aparecen en el calendario del móvil. Usa allí la contraseña de aplicación,
nunca tu contraseña de Kalmido.
