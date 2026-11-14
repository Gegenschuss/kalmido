<!-- Kalmido help, Spanish (2.1086.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the interface shows it.
Check: python3 tools/check_userhelp.py. -->

<!-- help: files#how-to-set-up-a-scan-inbox src=b33c638618 -->
## Configurar una bandeja de escaneo

Una bandeja de escaneo envía los escaneos nuevos de una carpeta de tu ordenador directamente a tus documentos.

1. Abre **Ajustes** > **Integraciones** y busca **Documentos: entradas**.
2. En **Vigilante de carpetas**, descarga el programa para tu ordenador (Mac o Windows).
3. Abre **Nueva bandeja de escaneo**, escribe un **Nombre**, elige la carpeta en **En la carpeta** y pulsa **Crear bandeja**.
4. Kalmido muestra el **Código de configuración** solo esta vez. Pulsa **Copiar**, inicia el programa, pega el código y elige
   la carpeta que quieres vigilar.

Qué pasa después: cada archivo nuevo de esa carpeta se sube, se lee y se ordena en tus documentos. Encuentras la bandeja en el
mismo lugar para cambiar la carpeta, prolongarla un año o revocarla. Solo tú creas una bandeja de escaneo, nunca un agente.

<!-- help: files#how-to-add-documents-and-find-them-again src=4520b96808 -->
## Añadir documentos y volver a encontrarlos

1. Abre **Archivos** > **Documentos**.
2. Pulsa **Añadir documentos** y elige PDF o fotos, o arrástralos a la página. En el móvil, **Escanear** fotografía una carta.
3. Escribe una palabra en **Buscar en los documentos…**; la búsqueda también encuentra palabras dentro de las cartas.

Qué pasa después: Kalmido lee cada documento y rellena fecha, importe y remitente. Lo que no tiene claro espera en
**Por revisar**: ábrelo, corrige lo que falle y pulsa **Revisado** (o **Aceptar todo** para las sugerencias).

<!-- help: files#how-to-share-a-folder src=f6f99fa88e -->
## Compartir una carpeta

1. Abre **Archivos** y el menú **Más** (⋯) de la carpeta, luego **Compartir…**.
2. En **Compartir con…** elige una persona, un grupo o un agente.
3. Elige **Puede ver** o **Puede editar**, pulsa **Añadir** y luego **Listo**.

Qué pasa después: la persona ve la carpeta y todo lo que contiene, también lo que se añada más tarde. Solo el propietario
puede compartir una carpeta.

<!-- help: agent-setup#how-to-create-your-personal-agent src=55f8406267 -->
## Crear tu agente personal

Un agente es un asistente (por ejemplo Claude) que trabaja en Kalmido con su propia cuenta y solo ve lo que compartes con él.

1. Abre **Ajustes** > **Agentes** y la pestaña **Configurar**.
2. En **Tus agentes personales** rellena **Nombre visible** y los otros dos campos y pulsa **Crear agente**.
3. En la ventana que se abre, elige tu **Ordenador** y la **Carpeta del proyecto** y pulsa **Crear comando**.
4. Pulsa **Copiar**, abre la terminal en ese ordenador, pega el comando y pulsa Intro. Luego **Listo**.

Qué pasa después: el agente aparece en **Tus agentes personales**. Todavía no ve nada: dale un proyecto o una carpeta. El
comando sirve una vez y solo unos minutos; **Configurar** en la fila del agente crea uno nuevo.

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=aaf357fa82 -->
## Dar a un agente acceso a un proyecto o una carpeta

Un proyecto:

1. Abre el menú (⋯) del proyecto y elige **Agente…**.
2. En **Agentes** elige el agente y confirma con **Compartir**.

Una carpeta en Archivos o Conocimiento:

1. Abre el menú (⋯) de la carpeta y elige **Compartir…**.
2. En **Compartir con…** elige el agente, **Puede ver** o **Puede editar**, pulsa **Añadir** y luego **Listo**.

Qué pasa después: el agente trabaja en ese proyecto o carpeta, y solo allí. Cada acceso de un agente queda en el historial;
una carpeta bloqueada nunca se comparte con un agente.

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=dfbe19a2e9 -->
## Aprobar lo que pide un agente

1. Cuando un agente necesita tu sí, aparece una tarjeta "… te espera" (en Hoy y en Agentes).
2. Pulsa **Aprobar** o **Rechazar**. Para una propuesta, primero **Revisar la propuesta**.

Qué pasa después: el agente sigue con lo que aprobaste; un paso rechazado no ocurre.

<!-- help: office#how-to-write-a-quotation src=c3eae76ef0 -->
## Escribir un presupuesto

1. Abre **Oficina** > **Presupuestos** y pulsa **Nuevo presupuesto**. El borrador se abre enseguida.
2. Elige el **Cliente**.
3. Añade líneas con **Añadir servicio**.
4. Cuando esté listo, pulsa **Cerrar**. Después, número, líneas e importes ya no cambian.
5. Pulsa **Enviar** para mandarlo por correo, o **Descargar PDF**.

Qué pasa después: el presupuesto está en la lista. Márcalo como enviado y luego como **Aceptado** o rechazado; de un
presupuesto aceptado sale la factura en un paso. Un borrador se ve con **Vista previa**.

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=faeae491ab -->
## Convertir un presupuesto en factura

1. Abre el presupuesto aceptado y pulsa **Crear factura**.
2. Elige el **Tipo de factura** y confirma.
3. Revisa la factura, pulsa **Cerrar** y luego **Enviar**.

Una factura sin presupuesto: **Oficina** > **Facturas** > **Nueva factura**.

Qué pasa después: la factura recibe su número al cerrarla, sin huecos. Sigue abierta hasta que se registra un pago.

<!-- help: office#how-to-record-a-payment src=6663fe7a8c -->
## Registrar un pago

1. Abre la factura cerrada y pulsa **Registrar pago**.
2. Revisa fecha e importe y pulsa **Registrar**.

O con el extracto: **Oficina** > **Banco** > **Importar extracto bancario** y acepta la sugerencia con **Asumir**.

Qué pasa después: la factura figura como pagada (o pagada en parte). Solo un administrador de la organización registra pagos.

<!-- help: tasks#how-to-add-a-task-with-a-date src=8a3685b666 -->
## Añadir una tarea con fecha

1. Pulsa en **Añadir tarea…** al pie del proyecto (en el móvil: el botón +).
2. Escribe la tarea como la piensas, por ejemplo "Llamar al dentista mañana 15h", o elige la fecha.
3. Pulsa Intro.

Qué pasa después: la tarea queda en el proyecto abierto (o en la **Cesta**) con su fecha y aparece ese día en **Hoy**. Para
cambiar la fecha, abre la tarea y pulsa su fecha: **Hoy**, **Mañana**, **Próxima semana** o un día del calendario.

<!-- help: tasks#how-to-make-a-task-repeat src=b22f5f0a3c -->
## Repetir una tarea

Una tarea recurrente vuelve sola: cada día, cada semana o según tu propia regla.

1. Abre la tarea y pulsa su fecha.
2. Elige en **Repetición**, por ejemplo **Diariamente**, o **Personalizado…** para tu propia regla.
3. Pulsa **Listo**.

Qué pasa después: al completar la tarea aparece la siguiente con la próxima fecha.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=d8a87df384 -->
## Asignar una tarea o compartir un proyecto

1. Compartir el proyecto: su menú (⋯) > **Compartir…**, elige la persona en **Compartir con…**, un rol (por ejemplo
   **Miembro**) y pulsa **Añadir**.
2. Asignar una tarea: abre la tarea, pulsa **Asignar** y elige la persona.

Qué pasa después: la persona ve el proyecto y recibe la tarea. Solo se puede asignar a personas del proyecto.

<!-- help: calendar#how-to-create-an-event src=5f4ebe03b3 -->
## Crear un evento

1. Abre **Calendario** y pulsa **Evento** (en el móvil: el botón +).
2. Rellena **Título**, **Empieza** y **Termina** y, si hace falta, **Repetición**.
3. Pulsa **Guardar**.

Qué pasa después: el evento está en el calendario y en tu móvil, si está conectado.

<!-- help: calendar#how-to-subscribe-to-another-calendar src=9f0cf2e56c -->
## Suscribirse a otro calendario

1. Abre **Calendario** > **Calendarios** > **Suscripciones…** (o **Ajustes** > **Integraciones** > **Calendarios**).
2. Pulsa **Añadir calendario**.
3. Pega el enlace del calendario y pulsa **Añadir**. Para una cuenta elige **Cuenta CalDAV** y **Buscar calendarios**.

Qué pasa después: sus eventos aparecen en tu calendario, solo para leer y solo para ti.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=73923b0417 -->
## Ver Kalmido en el móvil

1. Abre **Calendario** > **Calendarios** > **En el móvil…** (o **Ajustes** > **Integraciones** > **Apps de calendario (CalDAV)**).
2. Pulsa **Nueva contraseña de aplicación** y copia servidor, usuario y contraseña en los ajustes de calendario del móvil.

Qué pasa después: tus eventos y tareas con fecha aparecen en el calendario del móvil. Usa allí la contraseña de aplicación,
nunca tu contraseña de Kalmido.

<!-- help: wiki#how-to-write-a-knowledge-page src=122a76cda7 -->
## Escribir una página de conocimiento

1. Abre **Páginas de conocimiento** en la barra lateral y pulsa **Nueva página**.
2. Escribe el nombre de la página en **Nombre**. Una `/` crea carpetas: «Procesos/Lista» queda en la carpeta *Procesos*.
3. Escribe el texto. Con `[[` enlazas otra página.

Qué pasa entonces: la página se guarda sola y aparece en el árbol de la izquierda. Debajo de cada página, **Enlazada desde**
muestra las páginas que la enlazan.

<!-- help: wiki#how-to-share-a-page-read-only src=f589cec1bf -->
## Compartir una página solo para leer

1. Abre la página, abre su menú (⋯) y elige **Compartir…**.
2. Para una persona: elígela en **Elegir una persona…** (o escribe un correo) y pulsa **Añadir**.
3. Para quien no tiene cuenta: elige **Crear enlace público**, pon **Válido hasta** si quieres y copia el enlace.

Qué pasa entonces: la persona lee esta página (o toda la carpeta, con *Compartir carpeta…*) y nada más de tus páginas;
el enlace abre una página sencilla sin iniciar sesión. **Desactivar** termina un enlace al instante.

<!-- help: wiki#how-to-bring-back-an-earlier-version-of-a-page src=f736215a16 -->
## Recuperar una versión anterior de una página

1. Abre la página, abre su menú (⋯) y elige **Historial**.
2. Elige una versión de la lista: Kalmido muestra qué difiere del texto actual.
3. Pulsa **Restaurar**.

Qué pasa entonces: el texto antiguo vuelve a ser el actual como una versión nueva, así que no se pierde nada; la
restauración se puede deshacer.

<!-- help: sheets#how-to-make-a-table-with-a-formula src=b8056fbeac -->
## Crear una tabla con fórmula

1. Abre **Tablas**, pulsa **Nueva tabla**, ponle un nombre y pulsa **Crear**.
2. Pulsa **Añadir columna** y **Añadir fila** hasta que la cuadrícula encaje y escribe los valores en las celdas.
3. Empieza una celda con `=`, por ejemplo `=B2*C2` (horas por tarifa) o `=SUMA(C2:C9)`.

Qué pasa entonces: la celda muestra el resultado y se recalcula cuando cambia un valor; la tabla se guarda sola.

<!-- help: sheets#how-to-share-one-table src=e19d1eba08 -->
## Compartir una tabla

1. Abre la tabla, abre su menú y elige **Compartir…**.
2. Elige una persona o un agente en **Compartir con…**, luego **Puede ver** o **Puede editar** y pulsa **Añadir**.

Qué pasa entonces: la persona ve solo esta tabla, no el resto de tu espacio de trabajo; la encuentra en **Compartido conmigo**.
**Dejar de compartir** lo termina al instante.

<!-- help: team#how-to-write-to-a-colleague-in-the-team-chat src=d14fa10beb -->
## Escribir a alguien en el chat del equipo

1. Abre **Chat del equipo** y pulsa **Mensaje nuevo**.
2. Elige a la persona (o **Nuevo canal** para un canal).
3. Escribe el mensaje y pulsa **Enviar**.

Qué pasa entonces: la persona recibe el mensaje y una notificación; ves cuándo lo ha leído. Cada proyecto que compartes
tiene además su propio chat.

<!-- help: team#how-to-pin-a-message-or-answer-in-a-thread src=d57b9f4728 -->
## Fijar un mensaje o responder en un hilo

1. Abre el menú de un mensaje (en el móvil: mantenlo pulsado).
2. Elige **Fijar** para mantener un mensaje importante a la vista arriba de la conversación, o **Responder en el hilo** para
   responder sin llenar la conversación principal.

Qué pasa entonces: los mensajes fijados permanecen en la barra sobre los mensajes (como máximo cinco por conversación); un
hilo muestra las respuestas a ese mensaje y sus participantes reciben aviso.

<!-- help: team#how-to-invite-someone-without-an-account-by-a-link src=0b47d08909 -->
## Invitar con un enlace a alguien sin cuenta

1. En Ajustes > Cuenta elige **Buscar a una persona …**.
2. Elige **Invitar con enlace**, añade si quieres para quién es (solo lo ves tú) y elige **Crear enlace**.
3. Envía el enlace con **Copiar** o **Compartir**, o deja que la persona escanee el código QR.

Qué pasa después: quien abre el enlace crea una cuenta con su nombre y su dirección de correo y queda conectado contigo al
instante; recibes una notificación. El enlace funciona una vez y durante 14 días y solo se muestra justo después de crearlo;
**Retirar** termina un enlace abierto al instante. Quien ya tiene cuenta lo abre con la sesión iniciada y confirma la
conexión. Un administrador del servidor puede desactivar estos enlaces (Ajustes > Servidor > Inicio de sesión).

<!-- help: budget#how-to-start-a-household-budget src=1116c1b0a8 -->
## Crear un presupuesto doméstico

1. Abre **Presupuesto** (en el área **Hogar y vida**, se activa en *Ajustes > Módulos*) y pulsa **Crear presupuesto**.
2. Pulsa **Nuevo movimiento**, rellena **Importe**, la fecha y **Qué**, elige una categoría y pulsa **Guardar**.

Qué pasa entonces: el mes muestra lo **Recibido** y **Gastado** y lo que **Queda**; las categorías muestran lo gastado frente
al plan. Cada cambio se puede deshacer.

<!-- help: budget#how-to-add-rent-and-other-recurring-entries src=cd197ab4f2 -->
## Añadir el alquiler y otros movimientos recurrentes

1. En el presupuesto abre el menú (⋯), elige **Movimientos periódicos** y luego **Nuevo movimiento periódico**.
2. Rellena qué es y el importe, elige en **Con qué frecuencia** mensual, trimestral o anual y pulsa **Guardar**.

Qué pasa entonces: el movimiento aparece en **Pendiente este mes** cuando vence. Kalmido nunca lo contabiliza solo: pulsa
**Reservado** cuando el dinero realmente ha salido (o entrado).

<!-- help: budget#how-to-import-a-bank-statement-into-the-budget src=45308584bc -->
## Importar un extracto bancario al presupuesto

Kalmido no tiene acceso a tu banco: descargas el archivo tú mismo.

1. Descarga de tu banco la exportación CSV (o CAMT) del extracto de cuenta.
2. En el presupuesto abre el menú (⋯), elige **Importar archivo CSV** y el archivo en **Elegir archivos**.
3. Comprueba qué columna tiene la fecha, el importe y el texto, y confirma.

Qué pasa entonces: los movimientos nuevos entran en el presupuesto; los que ya estaban no se duplican. **Deshacer esta importación**
deshace toda la importación.

<!-- help: home#how-to-make-a-shopping-list src=c52a018554 -->
## Crear una lista de la compra

1. Abre **Hogar y vida**; si aún no hay lista, ofrece **Lista de la compra**. Púlsala.
2. Añade artículos como escribes una tarea; «2 l de leche» y «leche» cuentan como el mismo artículo.

Qué pasa entonces: los artículos se ordenan por secciones de la tienda (muévelo una vez y el siguiente va solo allí), y
quienes comparten la lista marcan en directo mientras compran.

<!-- help: home#how-to-sort-projects-into-folders src=9e6ec9656c -->
## Ordenar proyectos en carpetas

1. En la barra lateral abre el menú (⋯) de un proyecto y elige **Mover a carpeta…**.
2. Elige una carpeta o pulsa **Nueva carpeta…** y dale un nombre.

Qué pasa entonces: el proyecto queda en esa carpeta de la barra lateral. También puedes arrastrar proyectos entre
carpetas y compartir una carpeta entera de una vez (véase «Compartir una carpeta con otras personas»).

<!-- help: team#how-to-share-a-folder-with-people src=d68cfe0773 -->
## Compartir una carpeta con otras personas

1. En la barra lateral abre el menú (⋯) de una carpeta y elige **Compartir carpeta…**.
2. Elige una persona en **Compartir con…** y pulsa **Añadir**. Para agentes está la parte **Agentes** del mismo diálogo.

Qué pasa entonces: todos los proyectos de la carpeta quedan compartidos con ella, también los que añadas después.
**Dejar de compartir** lo termina al instante. Un proyecto suelto se comparte igual desde su propio menú.

<!-- help: team#how-to-give-people-without-an-account-a-public-link src=5c9b76a147 -->
## Dar un enlace público a personas sin cuenta

1. Abre el diálogo **Compartir…** del proyecto o de la carpeta y busca **Enlace público**.
2. Pon **Válido hasta** si el enlace debe caducar, cópialo con **Copiar el enlace** y envíalo.

Qué pasa entonces: quien tenga el enlace puede leer el proyecto, sin iniciar sesión, solo lectura, sin comentarios,
responsables ni archivos. **Desactivar** termina el enlace al instante.
