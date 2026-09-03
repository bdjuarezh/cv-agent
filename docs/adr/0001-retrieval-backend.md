# ADR 0001 — Backend de retrieval: NumPy en vez de una base vectorial gestionada

**Estado:** aceptado

## Contexto

El corpus narrativo (historia profesional, filosofía de trabajo) se trocea en ~200 chunks para
`search_profile`, la herramienta de respaldo para consultas semánticas de cola larga. Había que
elegir cómo indexar y buscar sobre esos vectores: una base vectorial gestionada (p. ej. Vertex
Vector Search), un almacén analítico con soporte vectorial (BigQuery `VECTOR_SEARCH`), o cómputo
directo en memoria.

## Decisión

Búsqueda exacta en NumPy (matriz de embeddings L2-normalizados, producto punto = coseno), con
BigQuery `VECTOR_SEARCH` documentado como backend alterno intercambiable detrás de la misma
interfaz (`Retriever` Protocol), y Vertex Vector Search evaluado y **descartado**.

## Por qué

Con $n\approx 200$ chunks y $d=384$, la búsqueda exacta es un producto matriz-vector de
$2nd\approx 1.5\times10^5$ FLOPs — del orden de 50 μs en NumPy. El cruce donde un índice
aproximado (HNSW/IVF) empieza a pagar está en $n\gtrsim 10^5$: tres órdenes de magnitud arriba de
este corpus.

Vertex Vector Search se descartó por costo fijo: el endpoint desplegado tiene un piso de
~$56/mes (instancia `e2-standard-2`, sin escala a cero) para un corpus cuyo índice cuesta
fracciones de centavo en construir. Queda como script escrito y **sin ejecutar** (evidencia de
que se evaluó, no una promesa de usarlo).

BigQuery `VECTOR_SEARCH` se probó como backend alterno midiendo paridad numérica (recall@5) y
latencia contra NumPy — a esta escala no puebla su índice vectorial (requiere ~10 MB / 5,000
filas) y cae a fuerza bruta, correcto y gratuito, pero sin ventaja sobre NumPy salvo si el corpus
creciera mucho o se necesitara consultarlo desde fuera del proceso del servicio.

## Consecuencias

- Cero dependencias externas ni latencia de red en el camino de retrieval.
- El `Retriever` Protocol permite cambiar de backend sin tocar el resto del código.

## Criterio de reversión

Revisar esta decisión si el corpus supera $10^5$ vectores, o si aparece un requisito de
multi-tenencia (varios corpus/usuarios sobre el mismo índice) que NumPy en memoria de un solo
proceso no pueda resolver limpiamente.
