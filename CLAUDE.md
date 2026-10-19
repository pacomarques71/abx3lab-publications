# ABX3Lab: instrucciones para colaboradores, incluido Claude

Antes de modificar código, leer CHANGELOG.md y README_PUBLICATIONS_UPDATE.txt.

1. GitHub Actions ejecuta scripts/update_publications.py seguido de scripts/enrich_publications.py.
2. La web WordPress/Oxygen lee data/publications.json y data/publications_2025.json; la configuración de proyectos es data/projects.json, y los ajustes editoriales manuales están en data/publication_extras.json.
3. La evidencia de financiación y licencia de imágenes está en data/publication_evidence.json; las imágenes automáticas se guardan en images/.
4. No editar los JSON generados como solución duradera: corregir scripts o su configuración.
5. La imagen manual de publication_extras.json tiene siempre prioridad sobre la automática.
6. Los proyectos deben relacionarse por códigos acreditados en Funding/Acknowledgements, nunca por temática. No reintroducir la herencia indiscriminada de proyectos antiguos.
7. No republicar imágenes sin una licencia de reutilización comprobable. Conservar la fuente y licencia.
8. OpenAlex TEI necesita un secreto OPENALEX_API_KEY en GitHub Actions, no guardar claves en el repo.
9. Ejecutar tests y verificar GitHub Actions después de modificar el pipeline.
10. **Actualizar CHANGELOG.md** con fecha, archivos afectados, propósito, decisiones y limitaciones cada vez que se modifique este flujo.

La falta de códigos en los metadatos no demuestra ausencia de financiación en los agradecimientos originales.
