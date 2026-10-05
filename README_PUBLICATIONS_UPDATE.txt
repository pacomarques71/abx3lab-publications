ABX3 LAB — SISTEMA DE PUBLICACIONES
===================================

ARCHIVOS
--------
data/publication_team.json
    Miembros usados para identificar publicaciones.
    ORCID=null = ORCID pendiente de confirmar/añadir.
    Esos miembros sí cuentan como coautores mediante aliases.

data/publications.json
    Dataset que debe leer la web.
    Está precargado con publicaciones verificadas desde 01/01/2026 con >=2 miembros.

data/excluded_publications.json
    Lista manual de DOI que nunca deben aparecer en la web.
    Para excluir una publicación, añade su DOI a este archivo y ejecuta el workflow.

scripts/update_publications.py
    Actualiza publications.json usando OpenAlex + Crossref.

.github/workflows/update-publications.yml
    Opcional: ejecuta el script cada lunes y también manualmente desde GitHub Actions.


ACTUALIZACIÓN MANUAL
--------------------
Desde la raíz del proyecto:

    python scripts/update_publications.py

Luego:

    git add data/publications.json
    git commit -m "Update publications"
    git push


REGLAS
------
MIN_PUBLICATION_DATE = 2026-01-01
MAX_PUBLICATION_DATE = fecha actual
MIN_GROUP_AUTHORS = 2

- Artículos y reviews.
- Se descartan publicaciones con fecha bibliográfica anterior al 01/01/2026.
- Se descartan publicaciones con fecha futura.
- Los DOI incluidos en data/excluded_publications.json se excluyen permanentemente.
- Si existen las versiones Wiley ange/anie del mismo artículo, se conserva anie (International Edition).
- Dedupe por DOI.
- Si hay volumen o número asignado, se prioriza la fecha del número (published-print
  de Crossref; en su defecto published/issued). Sin número, se prioriza la fecha online.
- publicationDate y year reflejan ese criterio bibliográfico. La primera aparición
  pública conocida se conserva por separado en onlinePublicationDate.
- La búsqueda de OpenAlex recorre todas las páginas sin cortar por fecha online;
  así se incluyen artículos online de 2025 asignados a números de 2026.
- Los ORCID conocidos descubren trabajos.
- Los miembros con ORCID=null pueden contar por aliases dentro de un trabajo ya descubierto.


LIMITACIÓN CON ORCID NULL
-------------------------
Si un futuro paper estuviera firmado exclusivamente por dos miembros que ambos tengan
ORCID=null, el script no podrá descubrirlo automáticamente hasta añadir al menos uno
de esos ORCID. No se intentan adivinar ORCID por nombre para evitar falsos positivos.


ACTUALIZACIÓN AUTOMÁTICA
------------------------
GitHub > Actions > Update publications > Run workflow

Además, el workflow se ejecuta cada lunes a las 06:00 UTC.

Si el hosting está conectado al repositorio y despliega tras cada push, la web se
actualizará automáticamente después del commit del workflow.


IMPORTANTE
----------
La página Publications NO debe llamar a OpenAlex ni Crossref desde el navegador.
Debe leer únicamente data/publications.json.

El script es quien actualiza ese JSON.
