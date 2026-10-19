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
