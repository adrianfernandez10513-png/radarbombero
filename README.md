# Radar de convocatorias: carga de datos

## Qué hace
1. Pide a la API del BOE el sumario de cada día y recorre la sección II.B (oposiciones y concursos).
2. Descarga el texto de las resoluciones candidatas y se queda con las que hablan de bombero o extinción de incendios.
3. Extrae entidad, plazas, grupo, sistema, tipo (bombero, conductor, especialista), tipo de documento y plazo estimado.
4. Agrupa los documentos en fichas (entidad + tipo) y calcula la fase.
5. Escribe `data/convocatorias.json` para la web y guarda todo en `data/docs.json`.

## Probar
    python test_etl.py                      # prueba con datos simulados
    python radar_etl.py --desde 2026-11-01  # primera carga real
Cambia `TU_EMAIL` en `UA` dentro de `radar_etl.py` antes de la primera carga real.

## Límites que conviene conocer
- El script y la prueba se han ejecutado solo con datos simulados; la primera carga real puede necesitar ajustes en los nombres de campos del JSON del BOE.
- El plazo es una estimación (días hábiles sin festivos) desde la publicación en el BOE. Compruébalo siempre con el boletín.
- Una misma entidad con dos procesos a la vez se mezcla en una ficha: sepáralos con `overrides.json` ({"BOE-B-2026-123": "madrid-conductor-2025"}).
- Provincia y comunidad quedan vacías; falta una tabla municipio, provincia y comunidad.
- Tasa y lista de admitidos de cada proceso no se extraen todavía.

## Boletines provinciales (BOP)
No hay un formato único. Para cada provincia: busca si el boletín ofrece RSS, y si lo hay añádelo a `sources.json`:
    [{"nombre": "BOP Jaén", "url": "URL_DEL_RSS"}]
Los que no tengan RSS necesitan un lector propio por boletín (HTML o buscador). Empieza por las provincias que más te interesen.

## Automático
`.github/workflows/update.yml` ejecuta el script cada día y guarda los datos en el repositorio. La web debe alojarse en GitHub Pages o Cloudflare (no en el artefacto de Claude) para poder leer `data/convocatorias.json`.
