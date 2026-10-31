"""2.449.0 (#3768): the samples in Spanish, translated when they were built (Kalmido never calls a language model). Same keys,
variables and [[optional parts]] as the English samples; the legal samples say on their second line that the translation
must be checked. SAMPLES = doctpl.DT_STARTERS + doctpl_samples.DMA_SAMPLES, BLOCKS = lettermail.LTB_STARTERS."""

SAMPLES = {
    "contract": ("Contrato de prestación de servicios", """# Contrato de prestación de servicios

Entre {{company.name}}[[, {{company.address}}]] (el prestador)
y {{client.name}}[[, {{client.address}}]] (el cliente)

## 1. Objeto
El prestador presta servicios al cliente[[ en el proyecto {{project.title}}]][[ según el presupuesto {{offer.number}}]][[ del {{offer.date}}]].

## 2. Remuneración
La remuneración se rige por el presupuesto[[ y asciende a {{offer.net}} más IVA]]. Las facturas se pagarán en un plazo de {{payment.days}} días sin descuento.

## 3. Colaboración
El cliente facilita a tiempo los documentos y la información necesarios.[[ Persona de contacto del cliente: {{client.contact}}.]]

## 4. Derechos de uso
Los derechos de uso se transmiten en el alcance acordado una vez efectuado el pago íntegro.

## 5. Disposiciones finales
Las modificaciones y ampliaciones deben hacerse por escrito. Si una cláusula fuera inválida, el resto del contrato seguirá siendo válido.

Fecha: {{today}}"""),
    "confirmation": ("Confirmación de pedido", """# Confirmación de pedido

Estimados señores:

muchas gracias por su pedido. Confirmamos el pedido[[ según nuestro presupuesto {{offer.number}}]][[ del {{offer.date}}]][[ para el proyecto {{project.title}}]].

- Cliente: {{client.name}}
- Persona de contacto: {{client.contact}}
- Importe del pedido: {{offer.net}} más IVA

Se aplican las condiciones del presupuesto. Revise los datos y avísenos si hay algo que no sea correcto.

Atentamente,
{{company.name}}"""),
    "nda": ("Acuerdo de confidencialidad", """# Acuerdo de confidencialidad

[Traducción automática, revisar antes de usar: después elimine esta línea.]

Entre {{company.name}}[[, {{company.address}}]]
y {{client.name}}[[, {{client.address}}]]

## 1. Información confidencial
Es confidencial toda la información que una parte comunique a la otra en el marco de la colaboración[[ en el proyecto {{project.title}}]] y que esté marcada como confidencial o sea reconocible como tal.

## 2. Obligaciones
Las partes utilizan la información confidencial solo para el proyecto, no la transmiten a terceros y la protegen con la diligencia adecuada.

## 3. Excepciones
Las obligaciones no se aplican a la información que sea pública, que una parte ya conociera legítimamente o que deba revelar por ley.

## 4. Duración
El presente acuerdo se aplica desde el {{today}} y finaliza tres años después del fin de la colaboración."""),
    "letter": ("Carta de presentación", """# [Asunto]

Estimados señores:

[Su texto]

No dude en ponerse en contacto con nosotros si tiene alguna pregunta.

Atentamente,
{{company.name}}"""),
    "reminder": ("Recordatorio de pago", """# Recordatorio de pago

Estimados señores:

quizá se les haya pasado por alto: todavía no hemos recibido el pago de la factura [número de factura] del [fecha de factura] por un importe de [importe].

Les rogamos que transfieran el importe pendiente antes del [fecha] a la cuenta indicada en la factura. Si ya han pagado, ignoren esta carta.

Atentamente,
{{company.name}}"""),
    "dunning": ("Requerimiento de pago", """# Requerimiento de pago

Estimados señores:

a pesar de nuestro recordatorio de pago del [fecha del recordatorio], la factura [número de factura] del [fecha de factura] por un importe de [importe] sigue pendiente.

Les rogamos que abonen el importe pendiente a más tardar el [plazo]. Transcurrido este plazo, nos reservamos el derecho de tomar otras medidas.

Si ya han pagado, ignoren esta carta.

Atentamente,
{{company.name}}"""),
    "termination": ("Rescisión", """# Rescisión del contrato [contrato / número de contrato]

Estimados señores:

por la presente rescindimos el contrato mencionado respetando el plazo de preaviso, con efecto a [fecha] o, subsidiariamente, en la siguiente fecha posible.

Les rogamos que nos confirmen por escrito la recepción de esta rescisión y la fecha de finalización del contrato.

Atentamente,
{{company.name}}

{{today}}"""),
    "authority": ("Poder", """# Poder

{{client.name}}
{{client.address}}

autoriza por la presente a

{{company.name}}
{{company.address}}

a realizar los siguientes actos en nombre del poderdante en el proyecto {{project.title}}:

- [acto 1]
- [acto 2]

Este poder es válido desde el {{today}} hasta el [fecha] y puede revocarse en cualquier momento. La subdelegación [no] está permitida."""),
    "handover": ("Acta de entrega", """# Acta de entrega

Proyecto: {{project.title}}
Entrega de {{company.name}} a {{client.name}}
Persona de contacto: {{client.contact}}
Fecha: {{today}}

## Entregado
- [objeto / entrega 1]
- [objeto / entrega 2]

## Estado y observaciones
[estado, piezas que faltan, puntos abiertos]

## Confirmación
El cliente confirma la recepción de los servicios indicados en el estado descrito."""),
    "credit": ("Carta de presentación de la nota de abono", """# Su nota de abono [número de nota de abono]

Estimados señores:

adjuntamos nuestra nota de abono [número de nota de abono] del {{today}} por un importe de [importe] correspondiente a la factura [número de factura] del proyecto {{project.title}}.

[Transferiremos el importe a su cuenta antes de la fecha / Compensaremos el importe con la próxima factura].

Atentamente,
{{company.name}}"""),
    "privacy_dpa": ("Contrato de encargo del tratamiento", """# Contrato de encargo del tratamiento

[Texto modelo, no es asesoramiento jurídico. Traducción automática, revisar antes de usar: adáptelo al encargo y elimine esta línea.]

Entre {{client.name}}, {{client.address}} (responsable del tratamiento)
y {{company.name}}, {{company.address}} (encargado del tratamiento)

## 1. Objeto y duración
El encargado trata datos personales por cuenta del responsable para los siguientes servicios: [servicios]. La duración se rige por la vigencia del encargo subyacente.

## 2. Naturaleza y finalidad del tratamiento
[naturaleza y finalidad, p. ej. almacenamiento, mantenimiento, análisis]

## 3. Tipos de datos e interesados
- Tipos de datos personales: [p. ej. datos de contacto, datos contractuales]
- Categorías de interesados: [p. ej. clientes, empleados]

## 4. Instrucciones
El encargado trata los datos únicamente siguiendo instrucciones documentadas del responsable (art. 28, apartado 3, letra a), del RGPD).

## 5. Confidencialidad
Las personas autorizadas para tratar los datos están obligadas a la confidencialidad (art. 28, apartado 3, letra b), del RGPD).

## 6. Seguridad del tratamiento
El encargado adopta las medidas técnicas y organizativas del art. 32 del RGPD: [medidas o anexo].

## 7. Otros encargados
Solo se recurre a otros encargados con la autorización previa del responsable (art. 28, apartados 2 y 4, del RGPD). Actualmente: [ninguno / lista].

## 8. Asistencia
El encargado asiste al responsable en las solicitudes de los interesados y en las obligaciones de los art. 32 a 36 del RGPD (art. 28, apartado 3, letras e) y f), del RGPD).

## 9. Supresión y devolución
Al finalizar los servicios, los datos se suprimen o se devuelven a elección del responsable, salvo que exista una obligación legal de conservarlos (art. 28, apartado 3, letra g), del RGPD).

## 10. Pruebas y auditorías
El encargado pone a disposición la información necesaria para demostrar el cumplimiento y permite la realización de auditorías (art. 28, apartado 3, letra h), del RGPD).

## 11. Notificación de violaciones
El encargado notifica sin dilación indebida toda violación de la seguridad de los datos personales de la que tenga conocimiento (art. 33, apartado 2, del RGPD).

Fecha: {{today}}"""),
    "privacy_info": ("Información sobre protección de datos", """# Información sobre protección de datos

[Texto modelo, no es asesoramiento jurídico. Traducción automática, revisar antes de usar: complételo y elimine esta línea.]

Información conforme a los art. 13 y 14 del RGPD para {{client.name}}

## 1. Responsable del tratamiento
{{company.name}}, {{company.address}}

## 2. Finalidades y bases jurídicas
Tratamos sus datos para preparar y ejecutar un contrato con usted (art. 6, apartado 1, letra b), del RGPD), para cumplir obligaciones legales como los deberes de conservación (art. 6, apartado 1, letra c), del RGPD) y cuando usted haya dado su consentimiento (art. 6, apartado 1, letra a), del RGPD).

## 3. Categorías de datos
[p. ej. nombre, dirección, datos de contacto, datos contractuales y de facturación]

## 4. Destinatarios
[p. ej. asesoría fiscal, proveedor de alojamiento como encargado del tratamiento]

## 5. Transferencias a terceros países
[ninguna / detalles]

## 6. Plazo de conservación
Conservamos sus datos mientras sean necesarios para estas finalidades y, más allá de ello, cuando existan plazos legales de conservación: [plazos].

## 7. Sus derechos
- Acceso, rectificación, supresión y limitación del tratamiento (art. 15 a 18 del RGPD)
- Portabilidad de los datos (art. 20 del RGPD) y oposición (art. 21 del RGPD)
- Retirada del consentimiento en cualquier momento con efecto para el futuro (art. 7, apartado 3, del RGPD)
- Reclamación ante una autoridad de control de protección de datos (art. 77 del RGPD)

## 8. Comunicación de datos
Necesitamos los datos requeridos para el contrato para celebrarlo y ejecutarlo. [delegado de protección de datos, si se ha designado]

Situación a: {{today}}"""),
    "privacy_consent": ("Consentimiento para el tratamiento de datos", """# Consentimiento para el tratamiento de datos

[Texto modelo, no es asesoramiento jurídico. Traducción automática, revisar antes de usar: adáptelo y elimine esta línea.]

{{client.name}}, representado por {{client.contact}}, consiente que {{company.name}} trate los siguientes datos personales:

- Datos: [datos]
- Finalidad: [finalidad]

## Carácter voluntario y retirada
El consentimiento es voluntario. Puede retirarse en cualquier momento sin indicar motivos con efecto para el futuro (art. 7, apartado 3, del RGPD), por ejemplo por correo electrónico a [dirección de correo electrónico]. La retirada no afecta a la licitud del tratamiento anterior a ella.

Encontrará más información en nuestra información sobre protección de datos.

Fecha: {{today}}"""),
}

BLOCKS = {
    "cancel": ("Rescisión", "por la presente rescindo el contrato mencionado respetando el plazo de preaviso en la fecha más próxima posible. "
                            "Le ruego que me confirme por escrito la rescisión y la fecha en que surte efecto."),
    "objection": ("Recurso", "por la presente interpongo recurso contra su resolución del [fecha], referencia [referencia]. Presentaré los "
                             "motivos por separado. Le ruego que me confirme la recepción de este escrito."),
    "reminder": ("Recordatorio de pago", "quizá se le haya pasado por alto: el importe de [importe] de nuestra factura [número] del [fecha] sigue "
                                         "pendiente. Le rogamos que lo transfiera antes del [fecha]. Si ya ha pagado, ignore esta carta."),
    "extension": ("Solicitud de prórroga", "le ruego que prorrogue el plazo del [fecha] hasta el [fecha], ya que todavía me faltan algunos documentos. "
                                           "Le agradezco su comprensión."),
}
