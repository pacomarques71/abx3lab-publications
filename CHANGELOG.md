# Registro de cambios de ABX3Lab Publications

Registro para coordinación entre ChatGPT, Claude y los editores de este repositorio. Consultarlo antes de modificar el pipeline y actualizarlo con cada cambio.

## 2026-11-25 — Imagen manual para 10.1039/d6qm00873a (Materials Chemistry Frontiers) y crédito de imágenes manuales

**Petición de Paco:** el artículo «Pd(iv) nano-perovskites catalyze hydroaddition reactions to alkynes» (Mater. Chem. Front., acceso cerrado, sin licencia CC) no tenía imagen; envió el resumen gráfico (TOC) para ponerlo a mano.

**Cambios:**
- images/manual-d6qm00873a-toc.webp: TOC enviada por Paco, recortada solo para quitar el marco discontinuo y el margen blanco (contenido completo, sin modificar), 1200 × 611 px.
- data/publication_extras.json: «image» e «imageCredit» («© The Royal Society of Chemistry and the Chinese Chemical Society 2026», la línea de copyright de la revista).
- scripts/enrich_publications.py: una imagen manual puede llevar «imageCredit» opcional en publication_extras.json; se copia a imageCredit y la web lo muestra fijo en el borde inferior, como en las imágenes de Wiley. Test nuevo (95/95 OK).

**Base:** la RSC permite a los autores reproducir partes de su artículo sin pedir permiso, con la referencia completa.

## 2026-11-25 — Imágenes de artículos de Wiley con licencia estándar (regla 7)

**Informe:** el artículo nuevo «High‐Performance Lead and Lead‐Free Inverted Perovskite Photodiodes…» (Adv. Funct. Mater., 10.1002/adfm.79536, 20/11/2026) salía sin figura. No era un fallo: Crossref da la licencia estándar de Wiley (termsAndConditions) y OpenAlex lo marca *bronze* sin licencia, así que la regla 7 lo dejaba sin imagen.

**Decisión de Paco:** admitir imágenes de Wiley con licencia estándar. El acuerdo de cesión de copyright / licencia exclusiva de Wiley permite a los autores reutilizar figuras sin pedir permiso, con crédito completo, sin modificarlas y sin fines comerciales; todos los artículos de la web los firman al menos dos miembros del grupo. En la figura debe verse, pequeño y en el borde inferior, «© 2026 Wiley‑VCH GmbH».

**Cambios:**
- scripts/enrich_publications.py: `wiley_standard_terms()` (DOI 10.1002/ sin ninguna licencia Creative Commons en Crossref ni OpenAlex) → licencia `wiley-standard-author-reuse`; se buscan TOC y Figura 1 por el mismo orden que siempre. `wiley_copyright()` lee el aviso «© AAAA Wiley-VCH GmbH / Wiley Periodicals LLC / John Wiley & Sons Ltd» del PDF (3 primeras páginas y la última); si no está, usa el año de publicación online y «Wiley‑VCH GmbH» para las revistas de Wiley‑VCH (lista WILEY_VCH_CODES) o «Wiley» para las demás. Se guarda en `image.credit` (publication_evidence.json) y en `imageCredit` (publications*.json). El guion de «Wiley‑VCH» es U+2011 (no se parte).
- Sin cambios: artículos de otras editoriales sin licencia CC y artículos con CC BY-NC/ND (también de Wiley) siguen sin imagen automática; la imagen manual de publication_extras.json sigue teniendo prioridad.
- CLAUDE.md (regla 7) y README_PUBLICATIONS_UPDATE.txt actualizados.
- Tests: tests/test_publication_wiley.py (9 nuevos); 92/92 OK.
- Web (Oxygen, Publicaciones ES/EN): el crédito del borde inferior de la figura usa `imageCredit` cuando existe («Imagen: Advanced Functional Materials · © 2026 Wiley‑VCH GmbH»), con el aviso de copyright sin pasar a mayúsculas.

**Afecta además a:** 10.1002/aenm.202503291 y 10.1002/anie.7703450, que tampoco tenían licencia CC y pasan a recibir imagen.

**Segunda corrección (mismo día):** en la primera ejecución (run 45591966254, commit del bot f2b1138), la Figura 1 de 10.1002/anie.7703450 salió cortada (solo la parte inferior). Es una figura vectorial y `first_figure_from_pdf` solo renderizaba los 225 pt inmediatamente encima del pie. Ahora prueba primero la región completa (desde el último párrafo de texto de la columna por encima del pie, o desde 50 pt bajo el borde superior, hasta 560 pt) y, si no parece una figura, la región corta de antes. IMAGE_MATCHER_VERSION 7 → 8: las Figuras 1 automáticas (no ACS) se revisan una vez. Test nuevo con una figura vectorial de 380 pt (93/93 OK).

**Tercera corrección (mismo día):** en la revisión por la versión 8 (run 45592664883, commit del bot bb36730), Europe PMC (www.ebi.ac.uk) no respondió (ReadTimeout) y 10.1002/advs.78211 y 10.1002/smsc.202400529 perdieron la Figura 1 original de PMC, que pasó a renderizarse desde el PDF. Ahora, en una revisión, una Figura 1 de PMC nunca se sustituye por una renderizada del PDF. IMAGE_MATCHER_VERSION 8 → 9 para recuperar esas dos con PMC ya operativo. Test nuevo (94/94 OK).
- Resultado de la versión 8 en las demás: anie.7703450 ya sale completa (paneles a y b); d5ma01122a y sstr.70540 se renderizan de nuevo con un encuadre casi igual (sstr.70540 sigue cortando el panel C por la derecha, como antes).

**Limitaciones:** el derecho de reutilización es de los autores y su alcance puede variar según la revista y el formulario firmado; conviene confirmarlo con el autor de correspondencia. La Figura 1 renderizada del PDF se publica entera (sin recortar paneles).

## 2026-11-15 — TOC y Figura 1: PMC Open Access y manuscritos aceptados

**Informe:** tras el arreglo de fechas, los dos artículos RSC que entraron en «The latest» (10.1039/d6ee05477c, 10.1039/d6qm00873a) salían con la ilustración de reserva, sin TOC ni Figura 1.

**Causas verificadas (diagnóstico en Actions, rama temporal diag-image, ya borrada):**
- pubs.rsc.org, doi.org, europepmc.org y la web de PMC devuelven 403 o una página HTML al runner de GitHub: no se puede leer la TOC de la web de la editorial.
- El único PDF accesible de d6ee05477c (repositorio EPFL / OpenAlex) es un manuscrito de 35 páginas sin TOC, con la Figura 1 en la página 8. first_figure_from_pdf solo miraba las 7 primeras páginas y exigía que el pie empezara el bloque de texto, lo que también fallaba con números de línea de los manuscritos aceptados («12 Figure 1.», d5el00064e) y con letras de panel unidas al pie («a) b) Figure 1.», d5ma01122a).
- 10.1039/d6qm00873a es de acceso cerrado (OpenAlex: closed; sin licencia CC en Crossref). Por la regla 7 no se republica ninguna imagen suya: sigue la ilustración de reserva. No es un fallo.

**Cambios (scripts/enrich_publications.py):**
- Nueva fuente: conjunto Open Access de PMC en AWS (pmc-oa-opendata.s3.amazonaws.com, público y accesible desde Actions). Europe PMC da el PMCID; el JATS identifica la TOC (abstract-type toc/graphical) y la Figura 1 (label «Fig. 1»), y se descargan las imágenes originales de la editorial (no las miniaturas GIF).
- Orden: TOC de la web de la editorial → TOC de PMC → TOC en el PDF → Figura 1 de PMC → Figura 1 renderizada del PDF. Si una imagen no se puede convertir, se prueba la siguiente fuente (antes se abandonaba).
- Figura 1 en el PDF: se buscan los pies línea a línea (FIGURE_ONE_LINE), con número de línea o letras de panel delante y exigiendo puntuación o mayúscula tras el 1 (no confunde «Figure 1b shows»), y se miran hasta 20 páginas.
- IMAGE_MATCHER_VERSION 6 → 7: las Figuras 1 automáticas se revisan una vez para buscar la TOC (las ACS siguen con su contador propio).
- Sin cambios: solo licencias CC reutilizables (sin NC/ND); la imagen manual de publication_extras.json siempre tiene prioridad.
- Tests: tests/test_publication_images.py (11 nuevos, sin red); 83/83 OK.

**Resultado en la prueba (rama diag-image):** d6ee05477c y d5el00182j → TOC de PMC; d5ma01122a y d5el00064e → Figura 1 del PDF (antes sin imagen); advs.78211 y smsc.202400529 → la misma Figura 1, ahora el archivo original de PMC; las demás Figuras 1 de Wiley no cambian.

## 2026-11-15 — Artículos RSC con fecha de solo año (salían como 1 de enero)

**Informe:** «Continuous optical–electrical field diagnostics separate environmental modulation from irreversible perovskite solar-cell failure», Energy Environ. Sci. 19 (21), 7447–7465, DOI 10.1039/d6ee05477c (Abargues, Boix) «no está en la web».

**Causa verificada:** el artículo SÍ se detectaba (está en data/publications.json desde el 12/10/2026), pero con publicationDate 2026-01-01. Crossref (RSC) solo deposita el año: published-online/published/issued = [[2026]], sin volumen; created = 2026-10-06. OpenAlex copia 2026-01-01. date_from_parts convertía [[2026]] en 1 de enero, así que el artículo quedaba el último de la lista ordenada por fecha: fuera de «Selección reciente», de la portada (3 más recientes) y fechado «enero de 2026» en el Archivo. Afecta igual a los demás artículos RSC (10.1039/d6qm00873a, d5ma01122a, d5el00182j; en 2025, d5el00064e, d4ma01150c, d5dd00099h).

**Arreglo (scripts/update_publications.py):**
- crossref_metadata guarda la precisión de cada fecha y marca publicationDateYearOnly cuando la fecha elegida es de solo año. Una published-online de solo año ya no se usa como fecha online.
- make_record: si la fecha es de solo año, usa la fecha exacta más temprana del mismo año entre OpenAlex (descartando su 1 de enero de relleno) y created (registro del DOI en Crossref, que en RSC coincide con la publicación online). Si el artículo salió online el año anterior (volumen del año siguiente), se mantiene el 1 de enero del volumen y la fecha online aparte, como antes.
- Cuando la editorial deposite una fecha de número con mes o día, se usa esa (criterio de siempre). Las fechas con mes (p. ej. Wiley [[2026, 7]]) no cambian.
- Tests: 4 nuevos en tests/test_publication_dates.py (72/72 OK), incluido el caso real de 10.1039/d6ee05477c.

**Verificado en Actions (run 43701844018, commit del bot 65ab7c4):** solo cambian las fechas RSC: d6ee05477c 2026-10-06, d6qm00873a 2026-10-28, d5el00182j 2026-01-21; en 2025, d5el00064e 2025-09-08 y d5dd00099h 2025-05-30. d5ma01122a y d4ma01150c conservan el 1 de enero del volumen (salieron online el año anterior). Ninguna publicación añadida ni quitada.

## 2026-10-19 — Detección automática de financiación e imágenes

- Se incorpora scripts/enrich_publications.py, ejecutado después de scripts/update_publications.py en GitHub Actions.
- FINANCIACIÓN: agrega extracción de Funding/Acknowledgements desde el HTML de la editorial, TEI XML de OpenAlex (si hay API key) y PDF de acceso abierto enlazado por la web. Compara los códigos contra data/projects.json. No infiere vínculos por temática.
- AUDITORÍA: data/publication_evidence.json documenta código, fuente, DOI, fecha de revisión y estado. Las publicaciones incorporan fundingEvidence y fundingStatus. No se almacena el texto completo de los agradecimientos.
- IMÁGENES: primero intenta TOC/abstract gráfico editorial; después primera figura raster identificada por la leyenda Figure 1 en el PDF OA. Solo archiva imágenes de publicaciones con una licencia de reutilización compatible; redimensiona a WebP de máximo 768 px y guarda en images/. Añade URL, tipo, fuente y licencia a la publicación.
- PRIORIDAD: las imágenes manuales de publication_extras.json prevalecen siempre. Si no hay imagen válida, permanece la ilustración de respaldo de la web. Los casos sin resolver se reintentan automáticamente.
- PRUEBAS: se cubren los dos DOI con financiación omitida (10.1002/sstr.202600020 y 10.1002/aelm.202500494), TEI, licencias, coincidencia de identificadores y prioridades manuales.
- RETENCIÓN: se elimina la herencia indiscriminada de proyectos antiguos, salvo conservación durante un fallo transitorio de Crossref para mantener compatibilidad. La evidencia positiva se conserva separadamente.
- WORKFLOW: instala dependencias y versiona los dos JSON, el fichero de auditoría y las nuevas imágenes. Soporta el secreto OPENALEX_API_KEY y variable CROSSREF_MAILTO.
- WEB: no se ha cambiado la maqueta de WordPress/Oxygen: ya interpreta image y projects.

### Limitaciones y verificación

- Una imagen visible o un PDF descargable no garantiza el permiso de redistribución. Solo guardar imágenes con licencia expresa compatible; respetar los créditos.
- Puede fallar la extracción de HTML por bloqueo de la editorial; pueden no existir figuras raster extraíbles del PDF.
- El uso de OpenAlex TEI requiere una clave gratuita configurada como secreto GitHub Actions. Sin clave, quedan habilitadas las otras fuentes.
- Comprobar la ejecución de Actions y los JSON generados. Que el código esté desplegado no demuestra que se hayan procesado correctamente todos los DOI.
- Claude y ChatGPT deben actualizar este registro en futuras modificaciones.


### Actualización de la implantación (19/10/2026, segunda revisión)

- El workflow incluye ahora fuentes adicionales: OpenAIRE Graph v4 (concesiones por DOI) y Europe PMC JATS para artículos de su subconjunto OA. Si hay API key, utiliza también el PDF almacenado por OpenAlex cuando la editorial rechaza la descarga directa. Se guarda el OpenAlex work ID para que la URL de contenido sea estable.
- Para artículos con figuras exclusivamente vectoriales, se intenta rasterizar una región gráfica de Figure 1; se rechazan regiones predominantemente textuales.
- GitHub Actions serializa y cancela ejecuciones anteriores para evitar conflictos cuando ChatGPT y Claude hacen commits a la vez.
- **Resultado comprobado:** tests unitarios aprobados y primera ejecución del enriquecimiento finalizada; la captura real de nuevas imágenes y siete relaciones omitidas todavía NO se ha conseguido.
- **Obstáculo operativo confirmado:** en el runner de GitHub, DOI.org, Wiley, RSC y ACS devuelven HTTP 403 a las peticiones de texto completo; el enlace PDF en la web no garantiza que un bot en GitHub Actions pueda descargarlo.
- **CONFIGURACIÓN PENDIENTE (humana, una sola vez):** crear una API key gratuita en https://openalex.org/settings/api y guardarla como secret del repositorio GitHub Settings > Secrets and variables > Actions > New repository secret, nombre exacto OPENALEX_API_KEY. No revelar ni subir la clave a GitHub en archivos. Este paso desbloquea OpenAlex XML y PDF. Reejecutar luego Update publications desde Actions para comprobar cobertura.
- Los casos siguen marcados como metadata-only mientras la fuente no sea accesible; la automatización nunca debe afirmar que el texto fue contrastado si no lo fue.


### 2026-10-19 — Corrección de falsos negativos de proyectos (segunda intervención)

**Informe del usuario:** el filtro WordPress no cambia de 9/20 publicaciones con proyecto tras ejecutar el pipeline con la API key OpenAlex; específicamente DOI 10.1016/j.solmat.2026.114703 debería reconocer HEPAFLEX y no aparece.

**Causa verificada en el run #30:** data/publications.json tiene projects=[] para ese DOI, data/publication_evidence.json tiene fundingStatus=metadata-only y OpenAlex Content devuelve HTTP 404 para XML/PDF de ese trabajo; el enlace OA disponible en OpenAlex es un preprint SSRN cuya landing page no aparece como pdf descargable. Otros DOI Wiley también reciben 404 desde Content y 403 desde el sitio editorial. El run terminó en éxito sin haber podido leer estos agradecimientos.

**Correcciones generales (sin hardcoding de DOI):**
- data/projects.json incorpora fundingAliases para nombres propios distintivos (incluido HEPAFLEX); solo se analizan estas palabras en secciones reconocidas de Funding/Acknowledgements, NUNCA en título o abstract. Los códigos grant siguen siendo la fuente preferente y se conservan las evidencias en JSON.
- scripts/enrich_publications.py examina secciones de financiación también en páginas iniciales del PDF, no solo las páginas finales, y amplia los PDF OA candidatos a copias de ubicaciones OpenAlex y de Semantic Scholar.
- tests/test_publication_enrichment.py comprueba el match exacto de HEPAFLEX, ausencia de falsos positivos en cadenas superpuestas, reconocimiento de Funding en primera página y fallback a repositorios.
- **ALCANCE HONESTO:** si el propio texto completo de un artículo o metadatos de financiación no están disponibles para el robot, ninguna regla de texto puede demostrar automáticamente la asociación. No se atribuyen trabajos por temática ni se fijan vínculos DOI -> proyecto manuales. Queda pendiente verificar en la ejecución real si una de las nuevas fuentes expone el artículo Rapid Photonic Processing.
- En caso de dudas, consultar el log del workflow y los campos fundingStatus/fundingEvidence; success no equivale a financiación comprobada.


### 2026-10-19 — Fuente oficial Elsevier y depuración de coincidencias

- Integración OPCIONAL del API oficial Elsevier TDM en scripts/enrich_publications.py para DOI 10.1016/*: lee el XML del artículo si existe autorización de acceso y extrae SOLO secciones de financiación/acknowledgements. El código no guarda el XML completo ni la clave; requiere secreto ELSEVIER_API_KEY en el repositorio GitHub (workflow actualizado). La API puede exigir habilitación de TDM y suscripción institucional; una clave no garantiza acceso desde el runner de GitHub.
- El parser XML reconoce variantes acknowledgement/acknowledgment, secciones Elsevier ce:section, ce:acknowledgment, JATS y TEI; se agregan tests con XML sintético.
- El extractor HTML evita buscar acrónimos en la totalidad del artículo al retirar el fallback al elemento article. No se atribuye proyecto si el nombre aparece solo en cuerpo/abstract/referencias.
- Para las publicaciones sin PDF editorial, se buscan ubicaciones OA de OpenAlex y Semantic Scholar. La financiación se busca en todas las páginas para cubrir las declaraciones de Funding al inicio del manuscrito, sin usar temas del artículo como evidencia.
- El identificador exacto de HEPAFLEX en data/projects.json es 101122345 y el alias específico es HEPAFLEX: coincidencias de palabra completa, únicamente en texto marcado como Funding/Acknowledgements.
- **Estado de verificación:** la última ejecución confirmada antes de estos commits (#30) mantenía 9/20 publicaciones con vínculos y 10.1016/j.solmat.2026.114703 sin proyectos (metadata-only). Nuevos runs en GitHub Actions están en cola; estas modificaciones no pueden declararse validadas en producción hasta que terminen. No prometer que el DOI quedará enlazado sin una fuente de financiación accesible al proceso.
- Guía para Elsevier: https://dev.elsevier.com/tecdoc_text_mining.html ; obtener API key oficial si la suscripción/condiciones lo permiten, guardar como GitHub Actions secret ELSEVIER_API_KEY y relanzar el workflow. No incluir la clave ni material protegido por copyright en la web.


### 2026-10-19 — Integración de Wiley TDM para vínculos automáticos

- scripts/enrich_publications.py: añade WILEY_TDM_TOKEN opcional. Para DOI de Wiley (10.1002/*), intenta descargar temporalmente el PDF desde el endpoint oficial https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}, usando el encabezado Wiley-TDM-Client-Token.
- Sigue las redirecciones sin reenviar el token a hosts externos. Rechaza documentos que no sean PDF y respuestas de acceso denegado, y registra solo el código HTTP y DOI (nunca el token).
- Analiza los agradecimientos del PDF para detectar automáticamente códigos de ayuda y nombres inequívocos de proyecto; la fuente se guarda como wiley-tdm en fundingEvidence sin almacenar texto completo protegido ni PDF en el repositorio.
- Estado wileyTdmStatus (success, unavailable, not-configured) en data/publication_evidence.json. Permite revisar trabajos anteriores cuando se añade el token posteriormente y reintenta casos con acceso fallido.
- .github/workflows/update-publications.yml: secreto WILEY_TDM_TOKEN en entorno de Actions; nunca almacenar en git ni en publicaciones.
- tests/test_publication_enrichment.py: pruebas unitarias para PDF directo, redirecciones sin credenciales, 404 y correspondencia de dos subvenciones en el artículo Memristors.
- **Acción del usuario**: en GitHub repository Settings > Secrets and variables > Actions, crear WILEY_TDM_TOKEN con el token de la página oficial Wiley TDM. Luego ejecutar Update publications UNA sola vez, y revisar el log para comprobar acceso real. No garantiza que GitHub Actions herede la suscripción del CSIC; Wiley devuelve 404 si no hay permiso de lectura desde el servidor.
- Para Elsevier, ELSEVIER_API_KEY es un secreto distinto; se necesita comprobar que está creado y que la clave tiene los permisos de ScienceDirect para recuperar XML desde los runners de GitHub.
- Documentación Wiley: https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining


### 2026-10-19 — Verificación del primer run con Wiley TDM y mejora de lectura del PDF

- La ejecución GitHub Actions #43 (39289221293) detectó WILEY_TDM_TOKEN, OPENALEX_API_KEY y ELSEVIER_API_KEY como configurados. Wiley TDM permitió descargar exitosamente PDFs, sin almacenarlos en GitHub. 40 tests aprobaron.
- **Resultados confirmados en datos:** DOI 10.1002/sstr.202600020 incorpora HEPAFLEX, CNS2023, FlexWin, InkFlex y Plan GenT, todos con fuente wiley-tdm y grant ID. Recuento de publicaciones con proyecto pasa de 9 a 10 (20 totales); HEPAFLEX pasa de 3 a 4 y aparecen tres imágenes nuevas adicionales.
- **Fallo aún abierto:** DOI 10.1002/aelm.202500494 descargó correctamente con Wiley, pero el PDF no produjo fundingEvidence porque el detector exigía encabezados reconocibles. La página oficial del editor muestra CNS2023-144270 y ESGENT/010/2024 en Acknowledgements: https://advanced.onlinelibrary.wiley.com/doi/10.1002/aelm.202500494
- Mejora general en scripts/enrich_publications.py: busca además cláusulas de financiación que mencionan códigos explícitos cerca de palabras como funded/grant/funding, incluso sin encabezado legible en PDF; excluye secciones de References. No fija asociaciones por DOI. Tests adicionales evitan falsos positivos por referencias y cubren ambos grants de Memristors.
- **Verificar la ejecución automática posterior** para comprobar si corrige Memristors. Si sigue sin detectar los grants pese al PDF disponible, hace falta diagnóstico del orden del texto extraído (sin almacenar PDFs protegidos) antes de afirmar que se ha solucionado.
- Elsevier sigue pendiente: la clave está disponible en Actions, pero Rapid Photonic Processing (10.1016/j.solmat.2026.114703) continúa metadata-only, sin HEPAFLEX, probablemente por restricciones de acceso al XML editorial.


### 2026-10-19 — Resultado de verificación posterior a token Wiley y parser flexible

- Run #44, https://github.com/pacomarques71/abx3lab-publications/actions/runs/39290190025, terminado SUCCESS, con pruebas, actualización, enriquecimiento y guardado superados.
- El parser flexible del PDF de Wiley no ha recuperado todavía los grants de 10.1002/aelm.202500494, aunque su PDF sí se descarga por Wiley TDM; sigue metadata-only y projects=[]. Hay que diagnosticar si PyMuPDF extrae realmente las cadenas de los grants o si el propio PDF carece de ellas. **No declararlo solucionado ni incluir vínculos manuales como sustituto de automatización.**
- 10.1002/sstr.202600020 sí está corregido automáticamente desde Wiley TDM con cinco grants. Recuento 10/20 publicaciones con proyectos (antes 9/20). 10.1016/j.solmat.2026.114703 continúa sin HEPAFLEX, a pesar de que la variable ELSEVIER_API_KEY está configurada. Acceso al XML del editor requiere investigación adicional.
- Todos los secretos configurados fueron detectados de forma segura en el run anterior; nunca volcar claves en logs.


### 2026-10-19 — Alta del proyecto SPIN en GitHub (sin cambios en WordPress)

- **Archivo modificado:** data/projects.json.
- Se añade el proyecto `spin` (SPIN), referencia exacta `PID2025-172217OB-I00`, para que el pipeline existente asocie automáticamente las publicaciones cuyo Funding/Acknowledgements cite ese código. URL de navegación: `/proyectos/#spin` (Claude ya se encarga de la parte WordPress; no se ha modificado).
- **Título:** Nanocomposites de perovskitas de estaño para una plataforma de fotónica integrada.
- **Subtítulo:** Hacia una nueva generación de dispositivos fotónicos sostenibles basados en perovskitas sin plomo.
- **Tipo:** Proyecto individual, Investigación orientada, tipo B.
- **Vigencia:** 01/09/2026 a 31/08/2029, 36 meses.
- **Entidad/centro:** Universitat de València, Instituto de Ciencia de Materiales (ICMUV).
- **IP-1:** Isaac Suárez Álvarez. **IP-2:** Teresa S. Ripolles.
- **Áreas:** Perovskitas sin plomo, Fotónica integrada, Guías de onda, Láseres, Fotónica topológica.
- La descripción científica íntegra de SPIN se conserva en el nuevo objeto de data/projects.json para que Claude pueda reutilizarla.
- **Decisión de detección:** no añadir fundingAliases con la palabra «SPIN» por ser un término corto y común en literatura científica; exigir el código oficial de financiación para evitar falsos positivos. No se han editado manualmente asociaciones de publicaciones ni código/diseño de la web.
- Añadir entradas en data/projects.json dispara GitHub Actions automáticamente; comprobar el run si se necesita corroborar el enriquecimiento futuro.


### 2026-10-19 — Diagnóstico independiente Wiley / Elsevier, y corrección de límites de grants

- Se añaden scripts/diagnose_funding_access.py y .github/workflows/diagnose-funding-access.yml. Flujo de solo lectura con permisos contents:read; no almacena PDFs, texto completo, fragmentos de los artículos ni claves. Los logs solo contienen HTTP, recuentos de páginas/caracteres y comprobaciones booleanas de referencias conocidas.
- Prueba efectiva https://github.com/pacomarques71/abx3lab-publications/actions/runs/39292674135: Wiley TDM descarga correctamente Memristors 10.1002/aelm.202500494 (PDF 9 páginas, ~54 mil caracteres de texto), y la extracción devuelve presentes CNS2023-144270 y ESGENT/010/2024. Elsevier API FULL para Rapid Photonic Processing 10.1016/j.solmat.2026.114703 devuelve HTTP 403 desde GitHub Actions aun con ELSEVIER_API_KEY configurada.
- Diagnósticos adicionales confirman ambos códigos en el texto de la sección de financiación de la página 8 de Wiley; el error no era el permiso Wiley ni la extracción del PDF sino el matcher grants_in_text.
- Causa exacta: normalizar el párrafo completo sin preservar fronteras pegaba los números posteriores (p. ej. grant seguido de año) y el filtro descartaba incorrectamente una referencia auténtica. Se cambia a búsqueda que conserva posiciones del texto original al comprobar los límites y tolera espaciado de letras/guiones por tipografía PDF. Tests específicos para códigos de CNS2023, Plan GenT, HEPAFLEX, variantes de puntuación y extensiones numéricas.
- La ejecución de Update publications #39293508508 confirmó la recuperación automática de CNS2023 en Memristors, pasando a 11/20 publicaciones con proyectos. La recuperación de Plan GenT está pendiente de validar en la ejecución tras la última corrección.
- **Elsevier pendiente de permisos**: la documentación https://dev.elsevier.com/tecdoc_text_mining.html establece que view=FULL puede devolver error sin entitlement de texto completo. La key no es equivalente a una autorización institucional. Solución: obtener acceso oficial desde IP institucional, token de institución X-ELS-Insttoken autorizado por Elsevier o un runner alojado en infraestructura de la organización, si sus normas lo permiten. No sortear restricciones con scraping. Documentación: https://dev.elsevier.com/documentation/ArticleRetrievalAPI.wadl y https://dev.elsevier.com/documentation/ArticleEntitlementAPI.wadl.
- No se ha modificado WordPress/Oxygen ni archivos de la página web. La interfaz queda bajo responsabilidad de Claude.


### 2026-10-19 — Cierre confirmado de Wiley Memristors; Elsevier limitado por autorización

- Ejecución de enriquecimiento selectivo https://github.com/pacomarques71/abx3lab-publications/actions/runs/39294766747, FINALIZADA SUCCESS. Se creó .github/workflows/enrich-existing-publications.yml para ejecutar manualmente el enriquecimiento de los JSON existentes sin repetir la búsqueda de autores en OpenAlex. Fue necesario porque la API de OpenAlex respondió HTTP 429 al ejecutar el flujo completo.
- **RESUELTO:** 10.1002/aelm.202500494 (Memristors) tiene los dos proyectos correctos: cns2023 (CNS2023-144270) y esgent (ESGENT/010/2024), ambos con evidencia fuente wiley-tdm y URL oficial. No se insertaron excepciones por DOI ni relaciones manuales.
- **Causa técnica:** en grants_in_text, normalizar el texto entero concatenaba los dígitos de un grant con fechas vecinas, causando falsos negativos; el primer parche recuperó CNS2023, pero el PDF Wiley introducía espacios anómalos dentro de algunas referencias. La implementación final hace match sobre texto normalizado conservando mapa a offsets originales para validar límites sin perder guiones, saltos o espaciado tipográfico. Tests 47/47 verdes.
- **Control de caché:** se añade FUNDING_MATCHER_VERSION=2 y fundingMatcherVersion en data/publication_evidence.json para reanalizar una vez cada artículo tras cambios relevantes de lógica, sin borrar evidencias. Revisión semanal posterior continúa normalmente. El nuevo enriched-only workflow comparte grupo de concurrencia con el workflow completo para evitar escrituras simultáneas en los JSON.
- **Recuento confirmado:** 20 publicaciones, 11 con proyectos; cns2023=8, esgent=6, hepaflex=4, flexwin=5, inkflex=4, phoenixpv=2.
- **PENDIENTE Elsevier:** 10.1016/j.solmat.2026.114703 (Rapid Photonic Processing) sigue fundingStatus=metadata-only, projects=[] aunque el usuario conoce que menciona HEPAFLEX. La API Elsevier FULL desde GitHub Actions devuelve explícitamente HTTP 403 aun con ELSEVIER_API_KEY. No atribuir proyecto por conjetura. Solicitar entitlement institucional en Elsevier (p. ej., acceso con X-ELS-Insttoken verificado o consulta desde IP institucional autorizada) y verificar lectura efectiva del XML antes de atribuir HEPAFLEX. Documentación Elsevier: https://dev.elsevier.com/tecdoc_text_mining.html y https://dev.elsevier.com/documentation/ArticleEntitlementAPI.wadl.
- **Alcance:** no se ha tocado ningún archivo de WordPress, Oxygen ni la web, y se han respetado las prioridades de imágenes manuales. La copia del texto íntegro solo se lee temporalmente en el runner; no se conserva en el repositorio público.


### 2026-10-20 — Mejoras de extracción automática del TOC / primera figura

- **Auditoría inicial de las cuatro publicaciones más recientes:** 10.1002/adom.71901, 10.1016/j.solmat.2026.114703, 10.1002/chem.202503192 y 10.1002/nap2.70196 tienen YA imágenes elegidas manualmente en data/publication_extras.json (tres graphical abstracts y una Figura 1). No se han sobrescrito; la prioridad editorial manual se conserva.
- **Diagnóstico real de tres PDFs Wiley con el token institucional**, sin almacenar ni publicar el PDF: https://github.com/pacomarques71/abx3lab-publications/actions/runs/39388153870 . El extractor de prueba recupera la primera figura de los tres: Advanced Optical Materials 481x681, Chemistry 1105x350 y Nano Advances 1014x583; no aparece un TOC inequívoco en ninguno de los PDFs. Las menciones a "graphical abstract" dentro de notas al pie NO equivalen a una imagen TOC.
- **scripts/enrich_publications.py:** selecciona TOC/graphical abstract explícitamente marcado en HTML (incluye lazy-loading, picture/srcset, alt/title/figcaption/meta específicos); si no está disponible, busca una imagen TOC inequívocamente etiquetada en el PDF (acepta tanto raster como gráficos vectoriales y descarta títulos incidentales y footers); si no existe, captura Figura 1 del PDF.
- **Calidad:** el recorte de Figura 1 se rasteriza de la página en sRGB sobre blanco (evita transparencias negras o artefactos por imágenes extraídas del PDF sin máscara). Los PNGs transparentes se componen sobre blanco antes de convertir a WebP. Imágenes con dimensiones insuficientes se rechazan, y nunca se usa la portada/logo genérico como supuesto TOC.
- **Reintento Wiley:** aunque la financiación ya esté revisada y Wiley figure con descarga correcta, las publicaciones sin imagen pueden descargar el PDF de nuevo para probar el nuevo selector. No se toca la lógica de la web WordPress/Oxygen.
- **Tests**: ver tests/test_publication_enrichment.py; se añadieron casos para etiquetas HTML/lazy images, exclusión og:image, TOC con imagen incrustada y con vector, falsos TOC en footers, transparencias blancas y reintento de PDF para imagen.
- **Límites reales:** Wiley TDM da acceso al PDF del trabajo pero no necesariamente al TOC editorial, que suele ser un gráfico aparte. Para las tres publicaciones Wiley recientes el único fallback probado en PDF es la Figura 1; las imágenes TOC manuales existentes son mejores y se mantienen. El cuarto DOI (Elsevier) continúa con HTTP 403 de full text API; la figura manual se conserva y no puede prometerse una extracción automática sin acceso autorizado y licencia de reutilización.
- **Control editorial:** no sobrescribir las imágenes manuales con versiones automáticas menos representativas. Si Claude añade un TOC manual para un artículo futuro, la fuente de verdad es publication_extras.json. Atribuir la imagen con licencia CC-BY solo cuando está justificada para esa fuente.
