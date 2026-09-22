# Predicción de tormentas mesociclónicas en Chile

### Un desafío abierto de datos, física atmosférica y aprendizaje automático

**Proyecto para el AWS Hackathon** · Documento de contexto, versión 1.0

---

## Índice

1. [El problema en una página](#1-el-problema-en-una-página)
2. [Física: ¿qué es un mesociclón y por qué importa?](#2-física-qué-es-un-mesociclón-y-por-qué-importa)
3. [El caso chileno: tornados donde "no debería haberlos"](#3-el-caso-chileno-tornados-donde-no-debería-haberlos)
4. [Los datos de entrada](#4-los-datos-de-entrada)
5. [Variables derivadas (*features*) que conviene calcular](#5-variables-derivadas-features-que-conviene-calcular)
6. [Cómo plantear el problema de aprendizaje automático](#6-cómo-plantear-el-problema-de-aprendizaje-automático)
7. [Arquitectura sugerida en AWS](#7-arquitectura-sugerida-en-aws)
8. [Tareas abiertas: por dónde empezar](#8-tareas-abiertas-por-dónde-empezar)
9. [Glosario](#9-glosario)
10. [Referencias y fuentes de datos](#10-referencias-y-fuentes-de-datos)

---

## 1. El problema en una página

En Chile ocurren tornados. Durante mucho tiempo se los consideró una rareza casi anecdótica, hasta que el **30 y 31 de mayo de 2019** dos tornados golpearon en menos de 24 horas las ciudades de **Los Ángeles** y **Talcahuano/Concepción**, en la Región del Biobío, dejando daños estructurales severos, heridos y una víctima fatal. El episodio obligó a reconocer algo que la comunidad meteorológica chilena venía documentando de a poco: el centro-sur de Chile tiene un régimen de convección severa propio, distinto al del *Tornado Alley* norteamericano, y prácticamente sin sistemas de alerta temprana.

Hoy existe un catálogo de **alrededor de 100 eventos tornádicos en Chile desde 2015**. Ese catálogo es la base de este proyecto, pero también su principal dificultad, porque:

> **El catálogo es una muestra de lo que se vio, no de lo que ocurrió.**

Un tornado solo entra a la base de datos si tocó tierra cerca de gente, si alguien lo filmó, si dañó algo que salió en la prensa. Una tormenta mesociclónica sobre el mar frente a Valdivia, sobre un bosque en la cordillera de Nahuelbuta o a las 4 de la madrugada en un campo de Osorno, sencillamente no existe en los registros. Muy probablemente hay **cientos de tormentas que se volvieron mesociclónicas y nunca fueron registradas**.

Esto define el desafío técnico con precisión:

- **Entrada:** campos vectoriales 4D de viento y termodinámica del reanálisis **ERA5** (latitud × longitud × nivel de presión × tiempo), más imágenes multiespectrales de **16 bandas del satélite GOES** cada 10 minutos.
- **Etiquetas:** ~100 casos positivos confirmados, sin negativos confiables.
- **Objetivo:** estimar, para cada tormenta o cada celda de la grilla, la **probabilidad de que el sistema desarrolle rotación organizada de mesoescala** (un mesociclón), potencialmente tornádica.
- **Producto final ideal:** un mapa de riesgo horario o sub-horario sobre Chile centro-sur, con antelación de algunas horas.

No se trata solo de reproducir los ~100 casos conocidos. Un modelo verdaderamente útil debería **encontrar los eventos que faltan en el catálogo**: señalar, en el archivo histórico, días y lugares donde las condiciones fueron indistinguibles de las de un tornado documentado. Eso convierte el proyecto en algo más cercano a un problema de **descubrimiento** que de clasificación clásica.

---

## 2. Física: ¿qué es un mesociclón y por qué importa?

### 2.1 Definición breve

Un **mesociclón** es una columna de aire en rotación, de entre **2 y 10 km de diámetro**, embebida dentro de una tormenta convectiva profunda y que se extiende verticalmente varios kilómetros. No es un tornado: es *mucho* más grande que cualquier tornado que pueda nacer dentro de él, y mucho más lento. Es, por así decirlo, el torno en el que se fabrica el tornado.

Una tormenta que posee un mesociclón persistente recibe el nombre de **supercélula**. Las supercélulas son el tipo de tormenta menos frecuente de los cuatro tipos clásicos (unicelular, multicelular, línea de turbonada y supercélula) y, al mismo tiempo, el más peligroso: concentran el granizo grande, las ráfagas destructivas y prácticamente todos los tornados fuertes y violentos.

Dos cifras útiles para calibrar expectativas:

| Magnitud | Valor típico |
|---|---|
| Diámetro del mesociclón | 2 – 10 km |
| Duración de una supercélula | 2 – 4 horas (casos extremos > 7 h) |
| Duración de un mesociclón individual | decenas de minutos a horas |
| Altura del tope nuboso | 12 – 21 km |
| Fracción de supercélulas que produce tornado | **≤ 30 %** |

Esa última fila es la razón de ser de este proyecto y también su trampa: **predecir el mesociclón no es predecir el tornado**. La rotación de mesoescala es una condición casi necesaria pero claramente no suficiente. Un modelo que prediga bien mesociclones dará muchas falsas alarmas de tornado — y aun así será enormemente más útil que no tener nada.

### 2.2 Los cuatro ingredientes

La convección severa organizada necesita cuatro cosas simultáneamente. Se las suele llamar "los ingredientes", y casi toda la predicción operacional consiste en medirlas:

1. **Humedad** en niveles bajos. Es el combustible: el calor latente que se libera al condensar el vapor de agua es lo que alimenta la corriente ascendente.
2. **Inestabilidad**. Si una burbuja de aire levantada desde la superficie se encuentra más cálida (y por tanto menos densa) que su entorno, sigue subiendo sola. La energía disponible para ello se mide con el **CAPE** (*Convective Available Potential Energy*), en J/kg.
3. **Disparo** (*trigger*). Algo tiene que dar el primer empujón hacia arriba: un frente frío, la brisa de mar, una cadena montañosa, la convergencia del viento en superficie.
4. **Cizalladura vertical del viento** (*wind shear*). El viento debe **cambiar de velocidad y/o de dirección con la altura**. Sin esto se puede tener una tormenta intensa, pero no una tormenta *rotatoria*.

Los tres primeros producen tormentas. **El cuarto es el que las hace girar**, y por eso es el corazón de este problema.

### 2.3 De la cizalladura a la rotación: inclinación y estiramiento

Éste es el mecanismo central. Vale la pena entenderlo bien porque dicta qué variables hay que calcular a partir de ERA5.

**Paso 1 — la cizalladura crea vorticidad horizontal.**
Imagine una ruedita de paletas flotando en el aire, con su eje horizontal. Si el viento sopla más fuerte arriba que abajo, empuja más la paleta superior que la inferior, y la ruedita empieza a girar sobre un eje horizontal. Eso es la **vorticidad horizontal**: una tendencia del aire a rotar en torno a un eje paralelo al suelo, generada directamente por el cizalle del viento.

> **Una aclaración que suele omitirse.** Los esquemas clásicos dibujan "tubos" de aire girando horizontalmente, como rodillos. Es una simplificación pedagógica útil, pero imprecisa: en un entorno horizontalmente homogéneo no existen tales tubos físicos. Lo que existe es una *tendencia local a rotar* distribuida en todo el campo de viento cizallado. La corriente ascendente reorienta esa tendencia, no un rodillo literal.

**Paso 2 — la corriente ascendente inclina esa rotación hacia la vertical (*tilting*).**
Cuando la corriente ascendente de la tormenta atraviesa la capa cizallada, tuerce el eje de giro desde la horizontal hacia la vertical. La rotación que antes era "de rodillo" pasa a ser "de trompo". La corriente ascendente completa empieza a girar.

**Paso 3 — la convergencia estira la columna y la acelera (*stretching*).**
Una vez que la columna rota, el aire que converge hacia su base la estira verticalmente. Por **conservación del momento angular** — el mismo principio por el cual una patinadora gira más rápido al cerrar los brazos — la columna, al hacerse más alta y delgada, **gira más rápido**. Se forma un mínimo de presión en su eje, que succiona más aire hacia arriba, que estira más la columna, que gira más rápido. Es un ciclo que se retroalimenta.

**Paso 4 — la rotación se organiza en un vórtice coherente.**
Inicialmente la rotación es desordenada: hay vorticidad de curvatura, asimetrías, ningún giro uniforme. El campo de presión de la corriente ascendente redistribuye esa vorticidad hasta que las parcelas interiores y exteriores alcanzan una tasa de rotación casi uniforme. En ese momento existe un **vórtice único y coherente**: el mesociclón está formado y la supercélula ha madurado.

Un detalle físico que importa para el diseño de *features*: el paso 2 es eficiente **solo cuando la vorticidad horizontal es *streamwise***, es decir, cuando su eje de giro está *alineado con el flujo* que entra a la tormenta. Si la vorticidad es puramente transversal (*crosswise*, perpendicular al flujo), inclinarla produce rotación pero no la correlación entre rotación y ascenso que define a una supercélula. Esto es exactamente lo que mide la **helicidad relativa a la tormenta (SRH)** — y es la razón por la cual la SRH es mejor predictor que el cizalle a secas.

### 2.4 Anatomía de una supercélula

Una supercélula no es una nube amorfa: tiene partes bien definidas, y varias de ellas dejan huella en las imágenes satelitales.

- **Corriente ascendente principal (*updraft*)**: la columna rotatoria. Puede alcanzar **50 m/s** en latitudes medias.
- **Base libre de precipitación**: la zona bajo la corriente ascendente donde entra el aire húmedo. Puede caer granizo grande desde un cielo que se ve despejado.
- **Nube pared (*wall cloud*)**: nube baja y rotatoria que cuelga de la base, en la frontera entre el ascenso y el descenso. Si la tormenta va a producir un tornado, típicamente muestra una nube pared que **persiste más de diez minutos**.
- **FFD (*forward flank downdraft*)**: la corriente descendente del flanco delantero, fría y húmeda, donde está la precipitación más intensa.
- **RFD (*rear flank downdraft*)**: la corriente descendente del flanco trasero. Es el elemento más sutil y probablemente el más importante: **los pulsos de la RFD suelen coincidir con la tornadogénesis**, porque aprietan y concentran la rotación preexistente cerca del suelo. En el radar produce la firma en forma de gancho.
- **Yunque (*anvil*)**: la meseta de hielo que se extiende cuando el ascenso choca con la tropopausa y pierde flotabilidad. Muy frío (**≈ −30 °C** o menos).
- **Tope penetrante (*overshooting top*)**: una cúpula que sobresale por encima del yunque, allí donde la corriente ascendente es tan potente que **penetra en la estratosfera**. Desde el suelo casi no se ve, pero **desde el satélite es inconfundible**: una burbuja sobre una superficie que, por lo demás, es lisa. Es una de las firmas satelitales más directamente utilizables.
- **Cap o inversión de bloqueo**: una capa cálida sobre aire frío que impide la convección prematura y permite acumular energía. Cuando se rompe, el desarrollo es explosivo.

**Tipos de supercélula.** Se clasifican según cuánta precipitación envuelve al mesociclón:

| Tipo | Característica | Riesgo dominante |
|---|---|---|
| **LP** (baja precipitación) | Núcleo de lluvia pequeño y separado del ascenso; aspecto de "sacacorchos" | Granizo grande; tornados raros y débiles; **puede no mostrar gancho en el radar** |
| **Clásica** | Precipitación "normal", estructura de libro de texto | Todo el espectro; el gancho es claro |
| **HP** (alta precipitación) | La lluvia **envuelve completamente al mesociclón** | Especialmente peligrosa: **el tornado queda oculto tras la lluvia**; inundaciones y ráfagas |

Para Chile esta taxonomía importa: un régimen marítimo y húmedo favorece estructuras del lado **HP**, donde el tornado es invisible desde tierra. Eso agrava el problema de detección y **refuerza el argumento para una alerta basada en modelos** en lugar de observación visual.

### 2.5 Tornadogénesis: los últimos kilómetros

El paso de mesociclón a tornado es la parte peor entendida de toda la cadena, y conviene ser honesto al respecto. Hay dos caminos distintos:

**Vía no supercelular** (*landspouts*, trombas marinas). Requiere un giro preexistente cerca de la superficie — típicamente en una línea de convergencia del viento — y un cumulonimbo encima cuya corriente ascendente estire ese giro hacia arriba. Estos tornados son **generalmente débiles y duran menos de 10 minutos**. Importa para Chile: buena parte de las trombas marinas del litoral probablemente sigue esta vía, que **no requiere mesociclón** y que un modelo entrenado sólo en cizalle profundo no va a capturar.

**Vía supercelular** (vía mesociclón). La RFD desciende y penetra por detrás en el centro del mesociclón; el aire frío y denso se enrolla en torno a la circulación existente, y la combinación ascenso + descenso concentra la rotación hasta escalas de decenas o centenas de metros. Estos tornados son **a menudo violentos y pueden durar más de una hora**.

La distinción tiene una consecuencia práctica directa: **el catálogo chileno casi con certeza mezcla ambas vías**, y valdría la pena etiquetarlas por separado si la evidencia lo permite.

### 2.6 Una advertencia crítica: estamos en el hemisferio sur

Casi toda la literatura, todos los índices y prácticamente todo el software de meteorología severa fueron escritos para el hemisferio norte. **En el hemisferio sur los signos se invierten.**

- Un mesociclón ciclónico en Chile gira **en sentido horario** (visto desde arriba), no antihorario.
- La **vorticidad ciclónica es negativa** con la convención matemática habitual.
- La **helicidad relativa a la tormenta (SRH) de los casos tornádicos es negativa**, y las supercélulas tornádicas favorecidas son las ***left-movers*** (que se desvían a la izquierda del viento medio), al revés que en EE.UU.
- Los índices compuestos — **STP, SCP, EHI** — están codificados con umbrales y signos del hemisferio norte.

> **Consecuencia operativa para el hackathon:** si se usa una librería como MetPy, SHARPpy o wrf-python tal cual, **los índices saldrán con el signo equivocado y el modelo aprenderá basura**. Hay que invertir explícitamente el signo de la SRH y de la vorticidad, o bien espejar el hodógrafo antes de calcular. Éste es probablemente el error silencioso más común y más costoso que se puede cometer en este proyecto.


---

## 3. El caso chileno: tornados donde "no debería haberlos"

### 3.1 Chile no aparecía en el mapa

Durante décadas, los atlas globales de tornados no mostraban nada en la costa occidental de Sudamérica. El "Corredor de los Tornados" sudamericano está del **otro lado del continente** — Argentina central, Uruguay, sur de Brasil, Paraguay — donde el aire cálido y húmedo del Amazonas choca con aire frío del sur sobre una llanura sin obstáculos. Chile, encajonado entre el Pacífico y los Andes, dominado por el anticiclón subtropical y con un clima notablemente estable, no encajaba en el molde.

El molde estaba mal.

El 30 y 31 de mayo de 2019 se produjeron **al menos siete tornados en 24 horas** entre los 36° y 38°S. Dos de ellos entraron en ciudades:

| | **Los Ángeles, Biobío** | **Talcahuano – Concepción, Biobío** |
|---|---|---|
| Fecha y hora | 30 mayo, 21:57 UTC (≈17:57 local) | 31 mayo, 18:00 UTC (≈14:00 local) |
| Intensidad | **EF2** | **EF1–EF2** |
| Duración | ~8 min | ~15 min |
| Trayecto | ~5,0 km | **17,1 km** |
| Viento estimado | 50–60 m/s (218 km/h, informe DMC) | 50–55 m/s (178 km/h, informe DMC) |

El saldo: **una persona fallecida**, decenas de heridos, cerca de 500 viviendas dañadas en el Gran Concepción, una nave industrial destruida, camiones volcados, y **unos 50.000 clientes sin electricidad** en Talcahuano. Cayó granizo de 2–3 cm y se acumularon hasta 180 mm de lluvia en dos días.

El tornado de Talcahuano tiene además una particularidad extraordinaria para la ciencia: **pasó a 400–450 metros de dos estaciones meteorológicas automáticas** del aeropuerto Carriel Sur. Los instrumentos registraron una **caída de presión de 2,1 hPa en 6 minutos** y ráfagas de 24,4 m/s. A partir de ese registro se pudo reconstruir el perfil del vórtice y estimar **50–55 m/s** en el radio de viento máximo, a unos 80 m del centro. Mediciones directas tan cercanas a un tornado son rarísimas en cualquier parte del mundo.

Y un detalle que define el carácter del problema chileno: **el tornado de Talcahuano nació como tromba marina**. Un piloto lo reportó sobre el agua antes de que tocara tierra en Caleta El Soldado. La convección severa chilena se fabrica, en buena medida, **sobre el océano**.

### 3.2 El régimen chileno: mucho cizalle, poco CAPE

Aquí está el hallazgo que hace de este un problema científico genuinamente interesante y no una simple transferencia de tecnología desde Estados Unidos.

En la imaginería popular, un tornado necesita un día de calor sofocante y un CAPE monstruoso — los 4.000 o 5.000 J/kg de una tarde de mayo en Oklahoma. **En Chile no pasa nada parecido.**

Durante el brote de 2019, el CAPE más inestable medido y reanalizado estuvo entre **200 y 500 J/kg**; los sondeos AMDAR tomados por aviones que aterrizaban en Concepción dieron **673 y 744 J/kg**. Son valores que en las Grandes Llanuras norteamericanas se considerarían apenas suficientes para una tormenta ordinaria.

Lo que sí había era **cizalladura**:

| Parámetro | Valor durante el brote de 2019 |
|---|---|
| MUCAPE | **200 – 1.000 J/kg** (bajo) |
| Cizalle 0–1 km | **12 – 20 m/s** (alto) |
| Cizalle 0–6 km | **18 – 21 m/s** (alto) |
| SRH 0–1 km | **−100 a −250 m²/s²** (parches de −600) |
| SRH 0–3 km | **−253 a −688 m²/s²** |
| Altura del LCL | **< 650 – 713 m** (muy bajo) |
| Jet de bajo nivel en 850 hPa | 20 – 25 m/s del NW |

Este es el régimen que la literatura llama **HSLC** — *High Shear, Low CAPE*, alto cizalle y bajo CAPE. Se define operacionalmente como SBCAPE ≤ 500 J/kg con cizalle 0–6 km ≥ 18 m/s y cizalle 0–1 km ≥ 10 m/s. No es exclusivo de Chile: es el mismo régimen del **sureste de Estados Unidos en invierno, de California, del sur de Australia y de las Islas Británicas**. Chile es un caso de **convección severa de costa occidental de latitudes medias**, y los análogos correctos están en esos lugares, no en Tornado Alley.

Hay que añadir un matiz importante sobre el "bajo" CAPE: **para la climatología chilena, 500 J/kg es un valor extraordinario**. El CAPE medio de fines de mayo en la región del Biobío es de apenas **15–45 J/kg**. No es que Chile tenga poco CAPE para hacer tornados; es que Chile normalmente no tiene *nada* de CAPE, y los días tornádicos son precisamente aquellos en que aparece algo.

Esto también explica por qué el momento del día importa tanto. La sensibilidad del CAPE al calentamiento superficial en este régimen es de aproximadamente **+500 J/kg por cada grado Celsius**. Un grado de más en la tarde duplica el combustible. Los siete tornados de 2019 ocurrieron todos entre las **18:00 y las 23:25 UTC**, es decir, aproximadamente **entre las 14:00 y las 19:25 hora local**: la ventana del calentamiento diurno.

> ### ⚠️ La consecuencia más importante para este proyecto
>
> **El Significant Tornado Parameter clásico no habría dado la alarma en mayo de 2019.** El STP, el índice compuesto más usado en Estados Unidos, pondera demasiado el CAPE frente al cizalle y la helicidad. Aplicado a Chile, sencillamente no ve estos eventos.
>
> Los índices calibrados para Chile son distintos:
> - **VGP₀₋₁ = √CAPE × cizalle₀₋₁ > 0,1 m/s²** — los cinco días tornádicos analizados (2008–2019) superan este umbral; Los Ángeles, el más intenso, supera **0,2** (Vicencio et al. 2021).
> - **SHERBE ≥ 1** y **STP (rama *left-mover*) ≤ −0,3** — ambos por encima del percentil 99 de la distribución chilena 1959–2021 (Marín et al. 2024). Nótese que el umbral es **−0,3**, no **+1**.
> - El **cizalle 0–6 km no discrimina** en Chile, porque en invierno extratropical casi siempre está disponible. **El que discrimina es el cizalle de 0–1 km** (> 12 m/s en los días tornádicos).
>
> Un modelo de *machine learning* que use los índices norteamericanos tal cual va a fallar. Un modelo que descubra por sí solo la combinación correcta sería un resultado valioso.

### 3.3 La receta sinóptica

Los estudios del brote de 2019 y la climatología de Marín et al. (2024) permiten escribir una receta razonablemente concreta de qué buscar en un mapa:

1. **Un ciclón extratropical o una baja cuasi-estacionaria frente a la costa** (~40–43°S, 75–80°W) que sostenga durante dos a cuatro días una **advección cálida del norte/noroeste** en superficie entre los 35° y 40°S. En 2019 esa baja, ocluida y de ~995 hPa, estuvo prácticamente inmóvil desde el 28 de mayo.
2. **Aire frío en niveles medios** (500 hPa) llegando en ondas cortas tras el frente. Nótese: la convección chilena severa es típicamente **post-frontal**, no pre-frontal como en Estados Unidos. A menudo bajo un **bloqueo anticiclónico al sur de los 45°S**, que parte el jet en dos ramas, o asociada a una **baja segregada** (*cutoff low*).
3. **La zona inestable en la salida polar de un *jet streak***, que aporta el ascenso sinóptico de gran escala.
4. **Un jet de bajo nivel del noroeste**, reforzado por el bloqueo del flujo contra los Andes.
5. En el caso del 31 de mayo, una **nube coma** (*comma cloud*) con una mesobaja asociada, que disparó una banda de celdas convectivas **sobre el océano, separadas unos 50 km**, que fueron entrando a tierra una tras otra.

### 3.4 Geografía: los Andes fabrican el cizalle

La cordillera no es un espectador pasivo. Los Andes, con más de 3 km de altura y orientados norte-sur, **bloquean el flujo del oeste** y lo obligan a canalizarse paralelo a la barrera, generando un **jet de barrera** (*barrier jet*) del nor-noroeste de 20–25 m/s en 850 hPa. Ese jet es precisamente lo que **amplifica el cizalle de bajo nivel y la helicidad**.

Esto no es especulación: Marín et al. (2021) lo comprobaron causalmente con experimentos de sensibilidad en el modelo WRF, reduciendo la topografía al 50 %, 25 % y 0 %. **Al bajar la cordillera, el cizalle y la SRH se desploman.** Los mismos experimentos muestran que la **temperatura superficial del mar modula la severidad** a través de la inestabilidad, y que — de nuevo — **el cizalle importa más que el CAPE**.

Hay además un contraste mar–tierra marcado y útil: el cizalle 0–1 km es de **5–10 m/s sobre el océano pero 10–20 m/s tierra adentro**, en parte por la fricción diferencial. Es decir, una celda que se forma sobre el mar **se vuelve más propensa a rotar justo al cruzar la costa**. Para un modelo de predicción, la franja costera entre los 36° y 40°S es la zona crítica.

### 3.5 Estacionalidad y geografía de los eventos

Ésta es quizá la diferencia más llamativa respecto del imaginario común: **los tornados chilenos son un fenómeno de otoño e invierno**, no de verano.

- **Otoño 46 % + invierno 43 % = 89 %** de los eventos catalogados.
- **Mayo es el mes más frecuente**, y el pico está concentrado entre **mediados de mayo y mediados de junio** — una "temporada de tornados" de aproximadamente **cuatro semanas** (Caballero-Morán & Rondanelli 2025). La probabilidad se mantiene elevada hasta agosto.
- La razón física es clara: es cuando llega **aire frío en altura sobre un océano y una superficie todavía relativamente cálidos y húmedos**. El máximo de CAPE ocurre a fines de mayo, el máximo de cizalle a fines de junio, y el máximo del VGP resulta del solapamiento de ambos, a comienzos de junio.

En cuanto a la geografía, los tornados se concentran entre los **36° y 42°S**, con máximos de densidad de reportes cerca de los **37°S** (Ñuble y Biobío) y los **41°S** (Los Lagos). Las **trombas marinas** son más típicas del invierno. La climatología de índices identifica dos focos:

- **~38°S, 72°W**, entre la Cordillera de la Costa y los Andes — coincide con el máximo de tornados observados.
- **~42,7°S, 74°W**, Isla de Chiloé — coincide con el máximo de trombas marinas.

### 3.6 El sesgo de reporte, cuantificado

El catálogo chileno reúne unos **43 eventos documentados entre 1633 y 2019** en la recopilación académica (y del orden de un centenar largo si se incluyen trombas marinas y las listas colaborativas más recientes). Pero su distribución temporal delata el problema:

- **86 % de los eventos son posteriores al año 2000.**
- **69 % ocurrieron entre 2015 y 2019.**

Nadie sostiene que los tornados chilenos se hayan multiplicado por cinco en cinco años. Lo que cambió fue **la densidad de teléfonos con cámara y de redes sociales**. El catálogo no mide tornados: mide **testigos con conexión a internet**. (Puede haber además una señal climática real superpuesta, pero es imposible separarla sin corregir primero la observabilidad.)

Los registros más antiguos son elocuentes precisamente porque son excepcionales: el de **Carelmapu, 14 de mayo de 1633**, que destruyó casi por completo un fuerte español y sobre el que el cronista Alonso de Ovalle escribió que cayó granizo "más grueso que balas de mosquete"; y el de **Concepción, 27 de mayo de 1934**, cuyos daños fueron cubiertos incluso por *The New York Times*. Ambos en mayo.

> **Y aquí está el dato que justifica todo este proyecto.** Caballero-Morán & Rondanelli (2025), analizando ERA5 entre 1959 y 2021, encontraron que **amplias zonas del sur austral de Chile presentan VGP, cizalle y helicidad perfectamente suficientes para generar tornados — y no tienen ningún registro documentado.** Su estacionalidad es incluso *más plana* que la del centro-sur. La conclusión de los autores es directa: se trata, casi con certeza, de **subregistro por baja densidad poblacional**.
>
> Es decir: no estamos especulando sobre eventos faltantes. **La literatura revisada por pares ya señaló dónde buscarlos.**

### 3.7 Chile no tiene radar

El último elemento del cuadro es el que convierte este problema académico en un problema urgente.

Vicencio et al. (2021) lo dicen sin rodeos: en 2019, Chile era **"un país sin radares meteorológicos y sin sistema de alerta de tornados"**. Toda la evidencia de que aquellas tormentas fueron supercelulares tuvo que reconstruirse *a posteriori* con imágenes GOES-16 cada 10 minutos, detección de rayos de la red WWLLN, perfiles AMDAR de aviones comerciales que casualmente aterrizaban en Carriel Sur, estaciones de superficie, videos de aficionados y simulaciones WRF.

La situación no ha cambiado sustancialmente. El proyecto de la Dirección Meteorológica de Chile contempla unos **ocho radares entre Valparaíso y Los Lagos**, a alrededor de **dos millones de dólares cada uno**, y sigue sin financiamiento. En 2025 ANID adjudicó, vía Fondequip, **el primer radar meteorológico del país** — móvil, sobre tráiler, unos US$700.000, liderado desde la Universidad de Valparaíso, con disponibilidad esperada hacia fines de 2026. Es un instrumento **científico y móvil**, no una red operacional.

Sin radar, la ventana de aviso de 20–30 minutos que ofrece el *nowcasting* Doppler se reduce a **5–10 minutos** con satélite y estaciones de superficie. La DMC y SENAPRED emiten hoy **avisos de condiciones favorables** para la formación de tornados y trombas por región, pero no un pronóstico del evento.

Un matiz honesto, sin embargo: **el radar tampoco sería una bala de plata**. En los entornos HSLC los mesociclones son **someros y transitorios**, y con frecuencia se forman y disipan en el lapso de unos pocos volúmenes de barrido. Incluso en el sureste de Estados Unidos, que sí tiene cobertura NEXRAD completa, estos eventos son notoriamente difíciles de avisar.

**Ésa es exactamente la brecha que un modelo basado en ERA5 y GOES puede ayudar a cerrar.** No reemplaza al radar; opera en una escala temporal distinta y complementaria — horas de antelación en lugar de minutos — e identifica *el entorno* favorable antes de que la tormenta exista. Y, de paso, puede reconstruir el catálogo histórico que Chile nunca tuvo.

---

## 4. Los datos de entrada

Tres fuentes, con naturalezas muy distintas: un **reanálisis** (el estado tridimensional de la atmósfera, reconstruido), un **satélite** (lo que se ve desde arriba, cada 10 minutos) y un **catálogo de eventos** (las etiquetas). Todo lo relevante está disponible públicamente y gran parte vive en S3 dentro del **AWS Open Data Program**, es decir, sin costo de transferencia si se procesa dentro de AWS en la región correcta.

### 4.1 ERA5: el estado 4D de la atmósfera

**ERA5** es el reanálisis atmosférico global de quinta generación del ECMWF. Un reanálisis no es un pronóstico ni una observación: es el resultado de correr un modelo de circulación global moderno *hacia atrás en el tiempo*, asimilando todas las observaciones históricas disponibles (radiosondas, satélites, aviones, boyas, estaciones). El producto es una reconstrucción física y dinámicamente consistente del estado completo de la atmósfera, hora por hora.

| Característica | Valor |
|---|---|
| Cobertura temporal | **Enero 1940 – presente** (extendido en tiempo casi real) |
| Resolución temporal | **Horaria** |
| Resolución horizontal nativa | ~31 km (0,28125°), espectral T639 |
| Resolución horizontal distribuida | **0,25° × 0,25°** (grilla lat/lon regular) |
| Niveles verticales | **137 niveles de modelo** (híbridos sigma-presión, tope 0,01 hPa); interpolados a **37 niveles de presión** (1 – 1000 hPa) |
| Latencia | ~5 días (versión preliminar **ERA5T**); ~2–3 meses para la versión final |
| Formato | GRIB1/GRIB2 nativo; **NetCDF-4** en las copias de AWS |

**Variables relevantes.** En niveles de presión: componentes del viento **u, v, w**, temperatura **t**, humedad específica **q**, geopotencial **z**, vorticidad potencial. En nivel único: presión a nivel del mar, temperatura y punto de rocío a 2 m, viento a 10 m y 100 m, temperatura superficial del mar, y **los índices de estabilidad CAPE y CIN** ya calculados por el ECMWF.

**Acceso en AWS.** Hay dos buckets y es importante no equivocarse:

```bash
# ✅ EL BUCKET A USAR — NSF NCAR, región us-west-2
aws s3 ls --no-sign-request s3://nsf-ncar-era5/

# ⚠️ DEPRECADO — solo 18 variables de superficie, sin datos en altura
aws s3 ls --no-sign-request s3://era5-pds/
```

El bucket `era5-pds` **está marcado como deprecado** y contiene únicamente 18 variables de superficie (viento a 10 m, temperatura a 2 m, presión, oleaje...). **No tiene niveles de presión, ni viento en altura, ni CAPE**: es inservible para este problema. La copia mantenida es `nsf-ncar-era5`.

Estructura de claves de `nsf-ncar-era5` (verificada con `ListBucket`):

```
e5.oper.an.pl/            ← análisis en niveles de presión  (u, v, w, t, q, z)
e5.oper.an.sfc/           ← análisis en superficie / nivel único
e5.oper.an.vinteg/        ← integrales verticales
e5.oper.fc.sfc.accumu/    ← pronóstico, acumulaciones (precipitación)
e5.oper.fc.sfc.instan/    ← pronóstico, instantáneas (CAPE, CIN)
e5.oper.fc.sfc.meanflux/
e5.oper.fc.sfc.minmax/
e5.oper.invariant/        ← campos invariantes (orografía, máscara de tierra)
```

con el patrón de nombre:

```
<prefijo>/<AAAAMM>/<prefijo>.<tabla>_<paramID>_<nombre>.<grilla>.<AAAAMMDDHH>_<AAAAMMDDHH>.nc

# ejemplo real:
e5.oper.an.pl/202401/e5.oper.an.pl.128_060_pv.ll025sc.2024010100_2024010123.nc
```

donde `128_060_pv` es tabla GRIB 128 / parámetro 60 / nombre corto `pv`, y `ll025sc` indica grilla 0,25° para campos escalares (`ll025uv` para campos vectoriales).

> **Advertencia de volumen.** Cada archivo de nivel de presión contiene **una variable, un día completo (00–23 UTC), el globo entero y los 37 niveles: ≈ 1,36 GB**. No hay *subsetting* del lado del servidor. Bajar 10 años × 6 variables ingenuamente son decenas de terabytes. La estrategia correcta es leer con **lectura perezosa por rangos de bytes** (`xarray` + `fsspec` + `h5netcdf`, o `kerchunk`/`virtualizarr` para construir un índice y leer sólo los *chunks* del recuadro chileno). Sólo se necesita aproximadamente el recuadro **17°S–56°S, 80°W–66°W**, que es una fracción minúscula del globo.
>
> Alternativa: el **Climate Data Store (CDS)** de Copernicus sí ofrece recorte geográfico del lado del servidor, a costa de una cola de peticiones. Para un archivo histórico grande conviene S3; para prototipar, el CDS.

**Lo que ERA5 *no* puede hacer.** Con 31 km de resolución y un paso horario, **ERA5 no resuelve un mesociclón**. Un mesociclón de 5 km de diámetro cabe dentro de una sola celda. Esto no es un defecto, es la premisa del proyecto: ERA5 describe el **entorno** — el escenario sinóptico y de mesoescala en el que la tormenta puede o no organizarse — y el satélite describe **la tormenta**. La pregunta es si el entorno predice a la tormenta.

### 4.2 GOES: la tormenta vista desde arriba, cada 10 minutos

Los satélites **GOES-R** (GOES-16 en adelante) son geoestacionarios y llevan a bordo el **ABI** (*Advanced Baseline Imager*), un radiómetro de **16 bandas** desde el visible hasta el infrarrojo térmico.

**Qué satélite mira a Chile.** El **GOES-East**, ubicado sobre el ecuador a **75,2°W** — es decir, casi exactamente sobre el meridiano de Chile. La serie temporal se reparte entre dos satélites:

| Bucket | Período | Estado |
|---|---|---|
| `s3://noaa-goes16/` | Dic 2017 – Abr 2025 | Archivo histórico de GOES-East |
| `s3://noaa-goes19/` | **Abr 2025 – presente** | GOES-East operacional (desde el 4 de abril de 2025, 15:00 UTC) |
| `s3://noaa-goes18/` | Ene 2023 – presente | GOES-**West** (~137°W): **no sirve para Chile** |
| `s3://noaa-goes17/` | congelado (Ene 2023) | fuera de servicio |

Todos en la región **us-east-1**.

**Las 16 bandas del ABI:**

| Banda | λ central (µm) | Tipo | Apodo | Resolución |
|---|---|---|---|---|
| 1 | 0,47 | Visible | Azul | 1 km |
| 2 | 0,64 | Visible | Rojo | **0,5 km** |
| 3 | 0,86 | IR cercano | "Veggie" | 1 km |
| 4 | 1,37 | IR cercano | Cirros | 2 km |
| 5 | 1,6 | IR cercano | Nieve/hielo | 1 km |
| 6 | 2,2 | IR cercano | Tamaño de partícula | 2 km |
| 7 | 3,9 | IR | Ventana de onda corta | 2 km |
| 8 | 6,2 | IR | **Vapor de agua, nivel alto** | 2 km |
| 9 | 6,9 | IR | **Vapor de agua, nivel medio** | 2 km |
| 10 | 7,3 | IR | **Vapor de agua, nivel bajo** | 2 km |
| 11 | 8,4 | IR | Fase del tope nuboso | 2 km |
| 12 | 9,6 | IR | Ozono | 2 km |
| 13 | 10,3 | IR | **Ventana larga "limpia"** | 2 km |
| 14 | 11,2 | IR | Ventana larga | 2 km |
| 15 | 12,3 | IR | Ventana larga "sucia" | 2 km |
| 16 | 13,3 | IR | CO₂ | 2 km |

Las bandas que más importan para convección severa son la **2** (textura y sombras del tope, sólo de día), las **8/9/10** (vapor de agua: revelan la circulación de niveles medios-altos aunque no haya nubes), la **13** (temperatura de brillo del tope: el termómetro de qué tan alto llegó la tormenta) y los pares **13−11** y **13−16**, que discriminan topes penetrantes.

**Cadencia.** En el **Modo 6** (operacional desde 2019): **disco completo cada 10 minutos**, CONUS cada 5 min, dominios de mesoescala cada 60 s. Chile está cubierto por el **disco completo**, es decir, **una imagen cada 10 minutos, 144 por día, las 24 horas**. Ésta es la resolución temporal que hace posible ver *cómo evoluciona* una tormenta.

**Estructura de claves:**

```
<Producto>/<Año>/<DíaDelAño>/<Hora>/<Archivo>

# ejemplo:
OR_ABI-L1b-RadF-M3C02_G16_s20171671145342_e20171671156109_c20171671156144.nc
   │                │   │  │              │              └─ creación del archivo
   │                │   │  │              └─ fin del barrido
   │                │   │  └─ INICIO del barrido: 2017, día 167, 11:45:34,2 UTC
   │                │   └─ satélite (G16/G19)
   │                └─ M3 = modo de barrido, C02 = banda 2
   └─ F = disco completo, C = CONUS, M1/M2 = mesoescala
```

> **Trampa práctica:** el directorio se organiza por hora de observación, pero el sello `c` (creación) puede caer en la hora siguiente. **Filtrar siempre por el campo `s`, nunca por `c`.**

**Productos recomendados:**

- `ABI-L2-MCMIPF` — *Multiband Cloud and Moisture Imagery, Full Disk*: **las 16 bandas calibradas en un solo archivo**. Muchísimo más eficiente que bajar 16 archivos `CMIPF` separados. Es el punto de partida natural.
- `ABI-L2-ACHAF` — altura del tope nuboso. Imprescindible (ver más abajo, corrección de paralaje).
- `ABI-L2-ACTPF` — fase del tope nuboso (hielo/agua).
- `ABI-L2-DSIF` — **índices de estabilidad derivados** (CAPE, índice de levantamiento, agua precipitable) estimados desde el satélite. Un contraste independiente de ERA5.
- `ABI-L2-DMWF` — **vientos derivados del movimiento de las nubes**. Es una observación real de viento en altura, con resolución mucho mayor que ERA5.
- `GLM-L2-LCFA` — rayos. Archivos cada **20 segundos** (180 por hora).
- `ABI-L1b-RadF` — radiancias crudas, si se quiere control total de la calibración.

**El problema de la geometría: Chile está en el borde.**

Éste es un punto técnico que hay que tomar en serio. El GOES-East está sobre el **ecuador**, y Chile se extiende hasta los **56°S**. El ángulo cenital local crece con la latitud:

| Lugar | Latitud aprox. | Ángulo cenital | Consecuencia |
|---|---|---|---|
| Arica | 18°S | ~20° | geometría cómoda |
| Santiago | 33°S | ~40° | paralaje ~10 km en un tope de 12 km |
| Chiloé | 42°S | ~50° | píxel efectivo notoriamente alargado |
| Punta Arenas | 53°S | ~60° | píxel IR de 2 km se comporta como ~2 × 4 km; paralaje ~20 km |

Dos efectos concretos:

1. **El píxel se estira.** Un píxel infrarrojo nominal de 2 km, visto a 60° de oblicuidad, cubre en realidad unos 2 × 4 km sobre el terreno. La resolución efectiva en el sur de Chile es peor que la nominal.
2. **Paralaje.** El tope de una tormenta está a 12–15 km de altura, y el satélite lo ve *de lado*. El tope aparece desplazado respecto de su posición real en superficie, en dirección **contraria al punto subsatelital** (hacia el sur-suroeste), por una distancia aproximada de `h · tan(θ)`: unos **10 km a 40°S y 20 km a 53°S**. Eso es **varias celdas de grilla**. Superponer ingenuamente una imagen GOES con una posición de tornado reportada, o con la grilla de ERA5, introduce un error sistemático mayor que el fenómeno que se quiere estudiar.

> **Recomendación:** aplicar corrección de paralaje explícita usando la altura de tope de `ABI-L2-ACHAF` junto con los parámetros de la proyección (`goes_imager_projection`, presente en cada archivo NetCDF) y el punto subsatelital (0°, 75,2°W). No tratar la lat/lon de la grilla fija como geolocalización en superficie.

También hay que notar que el **GLM** (detector de rayos) declara cobertura hasta ~52° de latitud: **Magallanes queda en el borde o fuera del campo de visión**, y en la zona Chiloé–Aysén la eficiencia de detección cae hacia el extremo bajo del rango 70–90 %. Es decir, **la ausencia de rayos detectados en el extremo sur no significa ausencia de rayos**. Ignorar esto genera un sesgo latitudinal que un modelo de ML aprenderá con entusiasmo y por las razones equivocadas.

Por último: existe un reprocesamiento de **GOES-16 ABI L1b** (2018 – fines de 2024) con calibración radiométrica y geométrica mejorada y estabilidad de navegación corregida. Para una climatología multianual conviene usarlo.

### 4.3 El catálogo de tornados: ~100 positivos y ningún negativo

La tercera fuente de datos es la lista de eventos confirmados en Chile desde 2015. Cada evento aporta, en el mejor de los casos, fecha, hora aproximada, coordenadas aproximadas y algún indicio de intensidad.

Sus limitaciones definen buena parte del diseño del proyecto:

- **Incompletitud selectiva** (*reporting bias*). La probabilidad de que un evento entre al catálogo depende de la densidad de población, de la hora del día y del año de ocurrencia (aumenta con la penetración de los teléfonos con cámara y de las redes sociales). Hay **más eventos registrados cerca de Concepción que en la cordillera** — y eso no dice nada sobre dónde ocurren los tornados.
- **Incertidumbre en hora y lugar.** Un reporte de prensa rara vez da la hora al minuto. Con GOES cada 10 minutos, un error de ±1 hora son ±6 imágenes.
- **Ausencia de negativos confiables.** "No hubo tornado ese día en ese lugar" no está observado: es una inferencia basada en que nadie reportó nada.
- **Mezcla de fenómenos.** Tornados supercelulares, trombas marinas, *landspouts* y probablemente algún *downburst* mal clasificado conviven en la misma lista.

Ninguna de estas limitaciones es fatal, pero todas deben tratarse explícitamente. La sección 6 propone cómo.

---

## 5. Variables derivadas (*features*) que conviene calcular

Ésta es la parte del proyecto donde la física se convierte en columnas de una tabla. La intuición de base es simple: **los campos crudos de ERA5 contienen la información, pero en una forma que un modelo con 100 ejemplos positivos no va a poder extraer por sí solo.** Con tan pocas etiquetas, la ingeniería de variables basada en física no es un lujo, es una necesidad: cada *feature* bien construida es conocimiento del dominio inyectado gratis al modelo.

### 5.1 Cinemáticos — los más importantes

**Cizalle de capa profunda (*bulk shear*).** La diferencia vectorial del viento entre dos niveles:

```
BWD(0–6 km) = | V(6 km) − V(superficie) |
```

Es el discriminante clásico entre tormentas ordinarias y organizadas. También conviene calcular **0–1 km** (relevante para tornadogénesis) y **0–3 km**. Nótese que es una **diferencia vectorial**, no una diferencia de rapideces: un viento que gira 90° sin cambiar de magnitud tiene cizalle grande.

**Helicidad relativa a la tormenta (SRH).** La integral, a lo largo de una capa, de la vorticidad horizontal proyectada sobre el flujo relativo a la tormenta:

```
SRH(0–h) = ∫₀ʰ (V(z) − C) · ω_h(z) dz
```

donde `C` es el vector de movimiento de la tormenta. Mide exactamente la cantidad de vorticidad ***streamwise*** disponible para ser inclinada hacia la vertical — es decir, el mecanismo de la sección 2.3, cuantificado. **Es probablemente la variable más informativa de todo el conjunto.** Calcular en las capas **0–1 km** y **0–3 km**.

> Requiere estimar `C`. El método estándar es el de **Bunkers**, que da dos soluciones: *right-mover* y *left-mover*. **En el hemisferio sur la supercélula favorecida es la *left-mover***, así que hay que usar esa rama — y recordar que la **SRH tornádica será negativa**.

**Vorticidad relativa** en 850, 700 y 500 hPa, y su advección. Y **vorticidad potencial** en 300–500 hPa, para identificar intrusiones estratosféricas y bajas segregadas (*cutoff lows*), que son un disparador sinóptico habitual en Chile.

**Forma del hodógrafo.** El hodógrafo es la curva que traza la punta del vector viento al subir en la vertical. Su **curvatura** distingue un perfil que sólo acelera con la altura (poco favorable) de uno que además gira (muy favorable). Se puede resumir en unos pocos números: curvatura integrada, longitud de arco, área encerrada en los primeros 3 km.

**Jet de niveles bajos.** Magnitud y altura del máximo de viento bajo 1,5 km — asociado al transporte de humedad y al cizalle cerca del suelo.

**Convergencia y divergencia.** Convergencia en 925/850 hPa (el disparo) y divergencia en 200–300 hPa (la "aspiradora" en altura que sostiene el ascenso).

### 5.2 Termodinámicos

- **CAPE** en sus variantes: **SBCAPE** (parcela de superficie), **MLCAPE** (capa mezclada, ~los primeros 100 hPa) y **MUCAPE** (la parcela más inestable, para convección elevada).
- **CAPE de niveles bajos (0–3 km)**. Para tornados, la CAPE que realmente importa es la de los **primeros 1–3 km**, porque es la que controla el *estiramiento* de la vorticidad cerca del suelo. En un régimen chileno de CAPE total bajo, ésta puede ser mucho más discriminante que el CAPE integrado.
- **CIN** (inhibición convectiva): cuánta energía hay que gastar para romper el *cap*.
- **Altura del LCL** (nivel de condensación por ascenso). Un LCL bajo — base de nube baja, aire húmedo cerca del suelo — es uno de los discriminantes tornádicos más robustos de la literatura.
- **LFC** (nivel de convección libre) y **nivel de equilibrio**, que fija la profundidad de la convección.
- **Tasa de caída de temperatura** (*lapse rate*) en 0–3 km y 700–500 hPa.
- **Temperatura en 500 hPa**: un indicador simple pero muy útil de aire frío en altura, el mecanismo dominante de inestabilización en Chile.
- **Agua precipitable** y humedad relativa en varias capas; la **depresión del punto de rocío en 700 hPa** (aire seco en niveles medios, que alimenta las descendentes).
- **DCAPE**: la energía disponible para las corrientes *descendentes*, ligada a la intensidad de la RFD y de las ráfagas.
- **Temperatura superficial del mar** y su gradiente respecto al aire: la fuente de calor y humedad para la convección que llega desde el Pacífico.

### 5.3 Índices compuestos

Combinan cizalle e inestabilidad en un solo número. Son atajos operacionales, no leyes físicas, **y todos vienen calibrados para el hemisferio norte y para entornos de CAPE alto**. Conviene calcularlos, pero con la expectativa de que en Chile haya que recalibrar sus umbrales.

- **EHI** (*Energy-Helicity Index*) = CAPE × SRH / 160000
- **SCP** (*Supercell Composite Parameter*)
- **STP** (*Significant Tornado Parameter*) — combina MLCAPE, cizalle 0–6 km, SRH 0–1 km, altura del LCL y CIN. **En Chile hay que usar la rama *left-mover* y el umbral ≤ −0,3**, no el +1 norteamericano.
- **BRN** (*Bulk Richardson Number*): razón entre flotabilidad y cizalle; discrimina el modo convectivo
- **SHERBE** (*Severe Hazards in Environments with Reduced Buoyancy*) — diseñado precisamente para entornos HSLC, que es el caso chileno. **Umbral propuesto para Chile: ≥ 1.**
- **VGP** (*Vorticity Generation Parameter*). La variante de bajo nivel **VGP₀₋₁ = √CAPE × cizalle₀₋₁** es, según Vicencio et al. (2021), el mejor discriminante disponible para Chile: **> 0,1 m/s²** en todos los días tornádicos analizados.

> **Prioridad para el hackathon.** Dado que el STP clásico *no* habría detectado el brote de 2019 (sección 3.2), conviene: (a) calcular SHERBE y VGP₀₋₁ desde el principio, no como añadido; (b) reajustar los coeficientes del STP con datos chilenos en lugar de heredar los originales. Un "STP austral" bien calibrado sería un resultado publicable por sí solo.

### 5.4 Satelitales (GOES)

**Estáticos, por imagen:**

- **Temperatura de brillo mínima** en la banda 13 dentro de la celda: qué tan alto llegó el tope. Más frío = más alto = ascenso más potente.
- **Diferencia tropopausa − tope**: cuánto sobrepasó la tormenta el nivel de equilibrio, usando la tropopausa de ERA5.
- **Detección de topes penetrantes** (*overshooting tops*): mínimos locales de temperatura de brillo rodeados de yunque más cálido, con textura característica en la banda 2.
- **Diferencias entre bandas**: `BT(6,2) − BT(10,3)` (el clásico indicador de tope que alcanza o supera la tropopausa; valores ≥ 0 son señal fuerte), `BT(11,2) − BT(10,3)`, `BT(13,3) − BT(10,3)`.
- **Firma en "V" o "U" fría** en el infrarrojo: el patrón que deja el flujo divergente en altura alrededor de un ascenso muy potente.
- **Pluma de cirros sobre el yunque** (*above-anvil cirrus plume*): en la literatura reciente es uno de los mejores precursores satelitales de tormenta severa.
- **Textura del yunque**: estadísticas de la gradiente y de la varianza local de la banda 2 — el yunque "burbujeante" de una tormenta vigorosa frente a la superficie lisa de una en decaimiento.
- **Área del tope por debajo de umbrales** de temperatura de brillo (−50 °C, −60 °C, −70 °C).
- **Fase y tamaño de partícula del tope** (bandas 11, 6; productos ACTPF y CPSF).

**Dinámicos — las tendencias son lo verdaderamente valioso:**

Aquí es donde la cadencia de 10 minutos justifica su existencia. Un tope frío no dice mucho; **un tope que se enfría rápido dice muchísimo**, porque mide directamente la aceleración de la corriente ascendente.

- **Tasa de enfriamiento del tope**: `dBT/dt` en ventanas de 10, 30 y 60 minutos. Enfriamientos más rápidos que **−4 K / 15 min** son un indicador establecido de convección en rápido desarrollo.
- **Tasa de expansión del área** del yunque frío.
- **Tasa de crecimiento del tope penetrante.**
- **Flujo óptico** entre imágenes consecutivas: da un campo de movimiento del tope nuboso, y su **rotación** (el rotacional del flujo óptico) es una medida directa — aunque indirecta en el sentido físico — de la rotación del yunque. Para un mesociclón bien desarrollado, **el yunque rota de forma visible en un *loop* de satélite**, y eso es precisamente lo que una red convolucional puede aprender.
- **Tasa de aumento de rayos** (*lightning jump*): un salto súbito en la frecuencia de descargas del GLM precede típicamente en varios minutos al tiempo severo en superficie. Uno de los indicadores de *nowcasting* mejor validados que existen. (Con la salvedad de cobertura en el extremo sur.)
- **Velocidad y dirección de propagación de la tormenta**, y **desviación respecto del viento medio de la capa**: una tormenta que se desvía sistemáticamente a la izquierda del viento medio en el hemisferio sur es, casi por definición, una candidata a supercélula. **Esta variable podría ser el detector de mesociclones más directo disponible en todo el conjunto de datos.**

### 5.5 Geográficos y temporales

- **Distancia a la costa** y **distancia a los Andes**; **altura del terreno** y pendiente.
- **Ángulo cenital del satélite** (para que el modelo pueda compensar la degradación geométrica) y **ángulo cenital solar** (las bandas visibles sólo existen de día).
- **Hora del día** y **día del año**, codificados con seno/coseno.
- **Densidad de población** — no como predictor físico, sino como **variable de control del sesgo de reporte**. Incluirla explícitamente permite que el modelo separe "aquí ocurren tornados" de "aquí se ven tornados".

### 5.6 Una nota sobre el enfoque

Existe un eje de decisión importante:

| Enfoque | Descripción | Cuándo conviene |
|---|---|---|
| **Basado en *features*** | Calcular decenas de índices físicos y alimentar un modelo tabular (gradient boosting) | Con ~100 positivos, es la opción más robusta y la más interpretable. **Empezar por aquí.** |
| ***End-to-end*** | Dar los tensores crudos (ERA5 4D + imágenes GOES) a una red convolucional 3D o a un transformer | Más potente en principio, pero con 100 ejemplos se sobreajustará sin remedio salvo con preentrenamiento |
| **Híbrido** | *Features* físicas del entorno (ERA5) + una CNN pequeña sobre recortes de GOES, concatenadas | Probablemente el mejor equilibrio. Es la ruta que recomendaríamos para el hackathon |

---

## 6. Cómo plantear el problema de aprendizaje automático

Éste es el punto donde el proyecto se vuelve realmente interesante, porque la formulación ingenua —"clasificador binario tornado / no tornado"— es incorrecta y va a fallar de maneras sutiles.

### 6.1 No es clasificación binaria: es aprendizaje con positivos y no etiquetados

Tenemos ~100 casos confirmados y **ningún caso confirmado negativo**. Un día sin reporte no es un día sin tornado: es un día sin reporte. Esto corresponde exactamente al marco de **PU learning** (*Positive-Unlabeled learning*), un área bien estudiada.

La consecuencia central es que el clasificador entrenado con "positivos vs. resto" **no estima la probabilidad de que haya tornado**, sino la probabilidad de que haya *tornado reportado*, que es el producto de dos cosas:

```
P(reportado | entorno) = P(tornado | entorno) × P(reportado | tornado, lugar, hora, año)
```

Si se modela explícitamente el segundo factor — con densidad de población, hora del día y año como covariables de observabilidad — se puede, bajo hipótesis razonables, **separar el fenómeno de su detección**. Técnicas aplicables: estimación de la constante de propensión de etiquetado (Elkan & Noto), *bagging* de PU learning, o modelos de ocupación tomados prestados de la ecología, que fueron inventados precisamente para "especies que están pero no se ven".

**El resultado más valioso del proyecto podría no ser el clasificador, sino su lista de falsos positivos de mayor confianza**: días y lugares donde el modelo está seguro de que hubo condiciones mesociclónicas y no hay reporte. Esos casos se pueden auditar uno a uno con las imágenes GOES, buscando la firma de rotación del yunque. Cada confirmación es un evento nuevo para el catálogo — y el catálogo ampliado permite reentrenar. Es un ciclo virtuoso.

### 6.2 Desbalance extremo

Con ~100 eventos en 10 años sobre una grilla de miles de celdas horarias, la tasa base es del orden de **10⁻⁶ a 10⁻⁷**. Implicaciones:

- **La exactitud (*accuracy*) es inútil.** Un modelo que diga "nunca" acierta el 99,9999 % de las veces.
- Métricas adecuadas: **AUC-PR** (no AUC-ROC, que es engañosamente optimista con desbalance extremo), ***Brier score***, **curvas de fiabilidad** (¿cuando el modelo dice 10 %, ocurre el 10 % de las veces?), y las métricas operacionales de la meteorología: **POD** (probabilidad de detección), **FAR** (tasa de falsas alarmas), **CSI** (*critical success index*) y **ETS**.
- **Muestreo negativo informado**: en vez de negativos al azar, usar *negativos difíciles* — días con tormenta convectiva pero sin ningún indicio de rotación. Eso obliga al modelo a aprender qué distingue una tormenta rotatoria de una tormenta fuerte, que es la pregunta real.

### 6.3 Validación: la trampa de la fuga temporal y espacial

Un **split aleatorio destruye este problema**. Dos horas consecutivas del mismo evento son prácticamente el mismo dato; si una cae en entrenamiento y otra en validación, el modelo parecerá excelente y no servirá para nada.

Lo correcto:

- **Separación por eventos completos**, no por instantes. Todo un brote va entero a entrenamiento o entero a validación.
- **Validación cruzada por bloques temporales** (dejar un año fuera cada vez), que además revela si el modelo es estable entre temporadas.
- **Zonas de amortiguación espaciales** si se valida por región.
- Conviene reservar **un evento notorio y bien documentado como prueba final ciega** — por ejemplo el brote de mayo de 2019 — y no mirarlo hasta el final.

### 6.4 Aumentación de datos y transferencia

Con 100 positivos, dos estrategias ayudan mucho:

1. **Preentrenamiento con datos de otra región.** Estados Unidos tiene decenas de miles de tornados catalogados en la base de datos del *Storm Prediction Center*, y Argentina/Uruguay —el "Corredor de los Tornados" sudamericano— tienen un régimen mucho más comparable al chileno. Entrenar en un dominio con muchas etiquetas y **ajustar finamente (*fine-tuning*) sobre Chile** es probablemente la mejor forma de aprovechar 100 ejemplos.
   *Ojo:* al transferir desde el hemisferio norte hay que **reflejar el hemisferio** (invertir el signo de la componente meridional del viento y de la helicidad), o el modelo aprenderá la quiralidad equivocada.
2. **Aprendizaje auto-supervisado sobre GOES.** Las imágenes no etiquetadas son esencialmente infinitas: 144 imágenes × 16 bandas × 365 días × varios años. Preentrenar un codificador con predicción del fotograma siguiente o con métodos contrastivos, y luego usar ese codificador con las 100 etiquetas, transforma el problema de "100 ejemplos" en "100 ejemplos sobre una representación ya buena".

### 6.5 Interpretabilidad

En una aplicación de alerta temprana, un modelo que no se puede explicar no se va a usar. Conviene incluir desde el principio **valores de SHAP** sobre las *features* físicas, **mapas de atención o de saliencia** sobre las imágenes GOES, y **casos análogos** ("este día se parece al 30 de mayo de 2019"). Si el modelo resulta apoyarse mayoritariamente en SRH de niveles bajos y en la tasa de enfriamiento del tope, eso no sólo da confianza: es un resultado científico.

---

## 7. Arquitectura sugerida en AWS

Una ruta pragmática, sin pretensión de ser la única:

**Ingesta.** Los datos ya están en S3 dentro del programa de datos abiertos: `nsf-ncar-era5` en *us-west-2* y `noaa-goes16/19` en *us-east-1*. **Trabajar en la misma región que el bucket** evita costos de transferencia entre regiones (lo que sugiere procesar GOES en *us-east-1*). Los buckets de GOES publican avisos por **SNS** cuando llega un objeto nuevo, lo que permite un canal casi en tiempo real vía Lambda/SQS.

**Extracción.** El recorte sobre Chile es vergonzosamente paralelo: una tarea por día. **AWS Batch** o **Lambda** con `xarray` + `fsspec` + `zarr`/`kerchunk`. Conviene rematerializar el recuadro chileno como un **Zarr** propio en S3: una vez hecho, el acceso pasa de minutos a milisegundos y todo el resto del trabajo se acelera.

**Cálculo de *features*.** `MetPy` para los índices termodinámicos y cinemáticos (**recordando la corrección de signos del hemisferio sur**), `xarray` + `dask` para paralelizar. Guardar como Parquet particionado por año/mes.

**Entrenamiento.** **SageMaker** para experimentos y búsqueda de hiperparámetros. Con ~100 positivos, el entrenamiento en sí es barato; lo caro es la preparación de datos.

**Servicio.** Endpoint de SageMaker o Lambda tras API Gateway; un mapa de riesgo en un sitio estático servido desde S3 + CloudFront.

**Costo.** La parte dominante es el cómputo de extracción, no el almacenamiento ni el entrenamiento. Empezar con un **subconjunto deliberadamente pequeño** —por ejemplo los ~100 eventos conocidos más 1000 días de control, sólo sobre el recuadro 33°S–45°S— permite recorrer el flujo completo de punta a punta en horas en lugar de semanas. Sólo después conviene escalar al archivo completo.

---

## 8. Tareas abiertas: por dónde empezar

El proyecto está abierto a cualquier persona interesada, con o sin formación en meteorología. Algunas líneas de trabajo, de menor a mayor dificultad:

**Accesibles**
1. **Curar y homogeneizar el catálogo** de eventos: fechas, horas UTC, coordenadas, tipo (supercelular / tromba marina / *landspout*), fuente y grado de confianza. Es la tarea de mayor impacto por unidad de esfuerzo, y no requiere saber meteorología.
2. **Construir animaciones GOES** de los eventos conocidos. Ver 20 casos en *loop* enseña más sobre el problema que cualquier documento — y sirve de material divulgativo.
3. **Visualizar el entorno sinóptico** de cada caso: mapas de 500 hPa, sondeos, hodógrafos.

**Intermedias**

4. Implementar la **extracción eficiente** del recuadro chileno desde ERA5 en S3 sin bajar el globo entero.
5. Implementar la **batería de índices con signos del hemisferio sur correctos**, y validarla contra casos conocidos.
6. Construir el **conjunto de negativos difíciles**: días con convección profunda pero sin rotación.
7. Implementar la **corrección de paralaje** para GOES sobre Chile.

**Avanzadas**

8. **Detección de rotación del yunque** por flujo óptico en los *loops* de GOES — un detector de mesociclones que no depende del catálogo de tornados y que podría generar miles de etiquetas nuevas.
9. **PU learning** con modelado explícito del sesgo de reporte.
10. **Preentrenamiento auto-supervisado** sobre el archivo GOES completo.
11. **Recalibración austral del STP/SCP** con los datos chilenos.

---

## 9. Glosario

| Término | Significado |
|---|---|
| **ABI** | *Advanced Baseline Imager*. El radiómetro de 16 bandas a bordo de GOES-R |
| **CAPE** | Energía potencial convectiva disponible (J/kg). El "combustible" de la tormenta |
| **CIN** | Inhibición convectiva. La energía que hay que gastar para iniciar la convección |
| **Cizalladura (*shear*)** | Cambio del viento con la altura, en magnitud y/o dirección |
| **Convección profunda** | Ascenso que atraviesa toda la troposfera; una tormenta |
| **ERA5** | Reanálisis global del ECMWF, 0,25°, horario, desde 1940 |
| **GLM** | *Geostationary Lightning Mapper*. Detector óptico de rayos en GOES |
| **Hodógrafo** | Curva que traza la punta del vector viento al ascender en la vertical |
| **LCL** | Nivel de condensación por ascenso. La altura de la base de la nube |
| **Mesociclón** | Columna rotatoria de 2–10 km dentro de una tormenta profunda |
| **Reanálisis** | Reconstrucción histórica del estado atmosférico con un modelo moderno |
| **RFD** | Corriente descendente del flanco trasero; clave en la tornadogénesis |
| **SRH** | Helicidad relativa a la tormenta. Mide la vorticidad alineada con el flujo |
| **Supercélula** | Tormenta con un mesociclón persistente |
| **Tope penetrante** | Cúpula que sobresale del yunque; señal de ascenso muy intenso |
| **Tornadogénesis** | El proceso de formación del tornado a partir del mesociclón |
| **Vorticidad** | Medida local de la rotación de un fluido |
| **Yunque (*anvil*)** | La meseta de hielo en el tope de la tormenta |

---

## 10. Referencias y fuentes de datos

**Datos**

- **ERA5 (NSF NCAR en AWS)** — `s3://nsf-ncar-era5/` (us-west-2) · DOI [10.5065/BH6N-5N20](https://doi.org/10.5065/BH6N-5N20) · [Registro AWS](https://registry.opendata.aws/nsf-ncar-era5/)
- **ERA5 (documentación ECMWF)** — [confluence.ecmwf.int · ERA5 data documentation](https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation)
- **Climate Data Store (Copernicus)** — [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu/) (con recorte geográfico del lado del servidor)
- **GOES en AWS** — `s3://noaa-goes19/`, `s3://noaa-goes16/` (us-east-1) · [Registro AWS](https://registry.opendata.aws/noaa-goes/) · [Documentación NODD](https://github.com/NOAA-Big-Data-Program/nodd-data-docs/tree/main/GOES)
- **Especificaciones del ABI y del GLM** — [goes-r.gov](https://www.goes-r.gov/spacesegment/abi.html)

**Literatura sobre convección severa en Chile** (imprescindible)

- **Vicencio, J., Rondanelli, R., Campos, D., Valenzuela, R., Garreaud, R., Reyes, A., Padilla, R., Abarca, R., Barahona, C., Delgado, R. & Nicora, G. (2021).** *The Chilean Tornado Outbreak of May 2019: Synoptic, Mesoscale, and Historical Contexts.* **Bulletin of the American Meteorological Society**, 102(3), E611–E634. [doi:10.1175/BAMS-D-19-0218.1](https://doi.org/10.1175/BAMS-D-19-0218.1) · [PDF libre](https://dgf.uchile.cl/rene/PUBS/Tornado_chile_2019.pdf)
  — **El punto de partida obligatorio.** Análisis completo del brote, contexto histórico del catálogo chileno, y la propuesta del VGP de bajo nivel.
- **Barrett, B. S., Marín, J. C. & Jacques-Coper, M. (2020).** *A multiscale analysis of the tornadoes of 30–31 May 2019 in south-central Chile.* **Atmospheric Research**, 236, 104811. [doi:10.1016/j.atmosres.2019.104811](https://doi.org/10.1016/j.atmosres.2019.104811) · [PDF](https://bsbarret.github.io/barrett_marin_jacquescoper_AtmosRes2020.pdf)
  — Caracterización del régimen HSLC y de la escala subestacional (MJO).
- **Marín, J. C., Gutiérrez, F., Gensini, V. A., Barrett, B. S., Pozo, D., Jacques-Coper, M. & Veloso-Aguila, D. (2024).** *Climatological Aspects of Notable Tornado Events in Chile.* **Monthly Weather Review**, 152(8), 1803–1819. [doi:10.1175/MWR-D-23-0249.1](https://doi.org/10.1175/MWR-D-23-0249.1)
  — **La fuente de los umbrales chilenos** (SHERBE ≥ 1, STP ≤ −0,3) y de la climatología de índices 1959–2021 con ERA5. Metodológicamente, el trabajo más cercano a este proyecto.
- **Caballero-Morán, V. & Rondanelli, R. (2025).** *Tornado Seasonality in Central-Southern Chile.* **Geophysical Research Letters**, 52, e2024GL110900. [doi:10.1029/2024GL110900](https://doi.org/10.1029/2024GL110900)
  — La temporada de ~4 semanas, y la identificación de zonas australes con entorno favorable pero **sin registros**.
- **Marín, J. C. et al. (2021).** *The tornadoes of 30–31 May 2019 in south-central Chile: Sensitivity to topography and SST.* **Atmospheric Research**.
  — Experimentos WRF que demuestran causalmente el rol de los Andes en generar el cizalle.
- **Aránguiz, R. et al. (2020).** *Damage assessment of the May 31st, 2019, Talcahuano tornado, Chile.* **International Journal of Disaster Risk Reduction**, 50, 101853. [doi:10.1016/j.ijdrr.2020.101853](https://doi.org/10.1016/j.ijdrr.2020.101853)
- **Vicencio, J. et al. (2019).** *Informe Especial: Tornados en la Región del Biobío.* Dirección Meteorológica de Chile. [Blog DMC](https://blog.meteochile.gob.cl/2019/06/14/en-busqueda-de-las-huellas-del-tornado-los-angeles-y-talcahuano-concepcion/)
- **Marín, J. C., Barrett, B. S., Gutiérrez, F. & Pozo, D. (2026).** *Mesoscale environments of tornadoes in Chile and along the U.S. west coast.* **Atmospheric Research**, 334, 109331.

**Contexto HSLC internacional**

- Sherburn, K. D. & Parker, M. D. (2014). *Climatology and ingredients of significant severe convection in high-shear, low-CAPE environments.* **Weather and Forecasting**, 29, 854–877. — El origen del índice SHERB.
- Coffer, B. E. et al. (2019). Sobre SRH 0–500 m como discriminante tornádico.
- Thompson, R. L. et al. (2003). — La formulación original del STP.
- Rasmussen, E. N. & Blanchard, D. O. (1998). — La formulación original del VGP.
- Hanstrum, B. N. et al. (2002, Australia); Monteverdi, J. P. et al. (2003, California); Clark, M. R. (2009, Inglaterra). — Los análogos de costa occidental.

**Física y fundamentos**

- Wikipedia (ES): [Mesociclón](https://es.wikipedia.org/wiki/Mesocicl%C3%B3n)
- Wikipedia (EN): [Mesocyclone](https://en.wikipedia.org/wiki/Mesocyclone) · [Supercell](https://en.wikipedia.org/wiki/Supercell) · [CAPE](https://en.wikipedia.org/wiki/Convective_available_potential_energy)
- Lemon, L. R. & Doswell, C. A. III (1979). *Severe Thunderstorm Evolution and Mesocyclone Structure as Related to Tornadogenesis*. **Monthly Weather Review**, 107, 1184–1197. — El modelo conceptual clásico de la supercélula.
- Browning, K. A. & Ludlam, F. H. (1962). *Airflow in convective storms*. **Quarterly Journal of the RMS**, 88, 117–135. — La primera supercélula descrita (Wokingham, 1959).
- Markowski, P. & Richardson, Y. (2010). *Mesoscale Meteorology in Midlatitudes*. Wiley. — El texto de referencia moderno.
- Bluestein, H. B. (2013). *Severe Convective Storms and Tornadoes*. Springer.
- Hersbach, H. et al. (2020). *The ERA5 global reanalysis*. **QJRMS**, 146, 1999–2049.

**Herramientas**

- [MetPy](https://unidata.github.io/MetPy/) — cálculo de índices termodinámicos y cinemáticos
- [xarray](https://xarray.dev/) + [fsspec](https://filesystem-spec.readthedocs.io/) + [kerchunk](https://fsspec.github.io/kerchunk/) — lectura perezosa desde S3
- [Satpy](https://satpy.readthedocs.io/) — lectura y composición de imágenes GOES
- [goes2go](https://github.com/blaylockbk/goes2go) — descarga simplificada de GOES desde AWS

---

*Documento preparado como material de contexto para el proyecto de predicción de tormentas mesociclónicas en Chile. Se agradecen correcciones, especialmente de la comunidad meteorológica chilena.*
