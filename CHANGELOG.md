# Registro de cambios de ABX3Lab Publications

Registro para coordinación entre ChatGPT, Claude y los editores de este repositorio. Consultarlo antes de modificar el pipeline y actualizarlo con cada cambio.

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
