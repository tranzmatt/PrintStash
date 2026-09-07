# Backend optimization opportunities

Estado: diagnóstico inicial generado a partir de una revisión estática de
`backend/app` en la rama `0.8.5` (2026-07-09). Las propuestas #1, #3, #2 y #4
se implementaron el mismo día (ver estado por fila en la tabla); el resto
sigue pendiente de valoración.

Contexto: el backend ya está notablemente optimizado — `model_views` documenta
y aplica el batching de facetas (N+1 tratado como bug), los uploads se
transfieren por chunks con límite de tamaño, SQLite corre con WAL +
`busy_timeout`, hay métricas Prometheus y request-logging con `request_id`.
Las oportunidades restantes son mayoritariamente de prioridad media/baja.

Filosofía local-first respetada: ninguna propuesta introduce dependencias
obligatorias de Redis/colas/cloud. Donde una infraestructura externa ayudaría,
se presenta como opción detrás de los seams existentes (`StorageBackend`,
`SessionFactory`, `RealtimeBus`, `TaskQueue`).

## Tabla de priorización

| # | Propuesta | Prioridad | Impacto | Esfuerzo | Área | Estado |
|---|-----------|-----------|---------|----------|------|--------|
| 1 | Batch de roles en `list_collections` (N+1 RBAC) | Alta | Alto en instalaciones multiusuario con muchas colecciones | Bajo | API taxonomy / RBAC | ✅ Implementado |
| 2 | Reducir hidratación en `filament/printer_profile_usage` (columnas en vez de `Metadata` completa) | Media | Crece linealmente con la biblioteca | Medio | Servicios / SQL | ✅ Implementado |
| 3 | RBAC duplicado en `model_views.detail` | Media | 2 queries extra por detalle | Bajo | Read-model | ✅ Implementado |
| 4 | Primer tick inmediato en `_gc_loop` | Media | Corrección operativa (trash GC nunca corre en contenedores efímeros <1h) | Bajo | Ciclo de vida | ✅ Implementado |
| 5 | ETag/304 en thumbnails y descargas S3 | Media | Menos bytes por visita a la grid | Medio | HTTP / archivos | Pendiente |
| 6 | Índices compuestos para consultas calientes de `files` | Baja–Media | Solo notable con >10⁴–10⁵ filas | Bajo | Índices | Pendiente |
| 7 | Consolidar los 8 counts de `vault_stats` | Baja | 8→2 round-trips por carga de dashboard | Bajo | SQL | Pendiente |
| 8 | Verificación JWT duplicada por request (middleware de audit + dependencia) | Baja | ~1 decodificación HMAC extra por request | Bajo | Auth | Pendiente |
| 9 | Eviction de claves inactivas en `RateLimiter` | Baja | Memoria acotada en procesos de larga vida | Bajo | Seguridad / memoria | Pendiente |
| 10 | `print_statistics` agregada en SQL | Baja | Solo con historiales de >10⁴ prints | Medio | Estadísticas | Pendiente |
| 11 | Total-count opcional en listados paginados | Baja | Habilita UI de paginación real | Medio | API / contrato | Pendiente |
| 12 | Cache LRU acotada para `_usage_cache` | Muy baja | Higiene de memoria | Trivial | Read-model | Pendiente |

---

## 1. `list_collections`: rol efectivo por colección (N+1)

- **Problema observado.** `GET /taxonomy/collections` resuelve
  `rbac.effective_collection_role(...)` dentro del list-comprehension final —
  2 queries por colección para usuarios no-superuser (lookup de la colección +
  grants), sobre una lista que ya cargó todas las colecciones accesibles.
- **Evidencia.** `backend/app/api/v1/taxonomy.py:139` (y el mismo patrón en
  `documents.py:96` para el detalle, y `taxonomy.py:174` en el create — estos
  dos son por-item, aceptables). El helper batched ya existe:
  `rbac.effective_roles_for_collections` (`modules/identity/rbac.py:126`), usado por
  `model_views.list_items`.
- **Impacto esperado.** Con 100 colecciones y un usuario con permisos: ~200
  queries → 3. Es el endpoint que alimenta el sidebar/outliner en cada carga.
- **Complejidad.** Baja — sustituir la llamada por-item por una llamada al
  helper existente antes del bucle.
- **Riesgos.** Ninguno funcional; el helper implementa la misma semántica de
  herencia por prefijo de path. Cubrir con un test de igualdad de resultados.
- **Alternativa local.** N/A (es puro SQL local).
- **Pasos.**
  1. En `list_collections`, llamar `effective_roles_for_collections(session, user, (c.id for c in cats))`.
  2. Mapear `roles.get(c.id)` en el comprehension.
  3. Test: usuario con grant en un subárbol; comparar roles con la versión por-item.

Nota adyacente (mismo endpoint): el cálculo de `model_count` por subárbol es
O(colecciones²) por los `startswith` anidados en memoria. Irrelevante hasta
varios cientos de colecciones; si crece, agrupar por prefijo con un solo pase
ordenado por path.

## 2. `filament_profile_usage` / `printer_profile_usage`: escaneo completo de Metadata

- **Problema observado.** Ambas funciones cargan **todas** las filas de
  `Metadata` de archivos vivos (`_live_file_metadata`) y hacen el matching
  perfil↔metadata en Python, O(archivos × perfiles), en cada
  `GET /filaments` y `GET /printer-profiles`.
- **Evidencia.** `backend/app/modules/library/model_views.py:247-287`; llamadas desde
  `api/v1/filaments.py:48` y `api/v1/printer_profiles.py:48`.
- **Impacto esperado.** Con 10k archivos, cada visita a Settings hidrata 10k
  filas ORM. Hoy es correcto pero es el punto de crecimiento lineal más claro
  del read-path.
- **Complejidad.** Media. El matching es difuso (nombre del perfil vs
  brand/type normalizados), no trivial de expresar en SQL portable
  SQLite/Postgres.
- **Riesgos.** Divergencia entre el matching SQL y el matching en Python que
  usa el cálculo de costes — deben compartir la misma normalización.
- **Alternativa local (recomendada primero).** No mover a SQL: reducir la
  hidratación. Seleccionar solo las columnas usadas
  (`material_brand, material_type, printer_model`) en vez de entidades
  `Metadata` completas — misma complejidad algorítmica, fracción del coste de
  serialización ORM. Si aún duele, agrupar por
  `(material_brand, material_type)` con `GROUP BY` y hacer el matching sobre
  los grupos (decenas) en vez de sobre archivos (miles).
- **Pasos.**
  1. Cambiar `_live_file_metadata` (o añadir variante) a `select(Metadata.material_brand, Metadata.material_type, ...)`.
  2. Para el caso `GROUP BY`: `select(cols, func.count()).group_by(cols)` y multiplicar el conteo por grupo.
  3. Test de regresión: los conteos por perfil no cambian sobre un fixture con marcas mixtas.

## 3. `model_views.detail`: resolución RBAC duplicada

- **Problema observado.** `detail()` llama `_effective_model_role` dos veces
  (guard de acceso y campo `effective_role` de la respuesta); cada llamada son
  2 queries. Además `tag_names_for` lanza una query aunque `Model.tags` ya se
  carga vía `selectin`.
- **Evidencia.** `backend/app/modules/library/model_views.py:558` y `:581`; `:582`.
- **Impacto esperado.** 3 queries menos por carga de detalle (el endpoint más
  visitado tras la grid).
- **Complejidad.** Baja. **Riesgos.** Ninguno.
- **Pasos.** Resolver el rol una vez en una variable local y reutilizarla;
  usar `sorted(t.name for t in m.tags)` como ya hace `list_items`.

## 4. `_gc_loop`: sleep-first retrasa el primer GC una hora

- **Problema observado.** El bucle duerme 3600 s **antes** del primer tick, así
  que el GC de la papelera y el pruning de deliveries no corren nunca en
  procesos que viven menos de una hora (redeploys frecuentes, dev), y tras un
  boot la papelera vencida espera una hora.
- **Evidencia.** `backend/app/main.py:111-124`.
- **Impacto esperado.** Corrección operativa; sin efecto en rendimiento.
- **Complejidad.** Trivial (ejecutar el cuerpo antes del sleep o mover el
  sleep al final). **Riesgos.** Un GC en el arranque compite con la carga de
  boot; despreciable porque ya corre en `asyncio.to_thread`.
- **Pasos.** Invertir el orden sleep/trabajo; smoke test de arranque.

## 5. Thumbnails y descargas: revalidación barata (ETag/304)

- **Problema observado.** `thumbnail_response` sirve con
  `Cache-Control: max-age=3600` pero sin ETag explícito. Con backend local,
  `FileResponse` de Starlette añade ETag/Last-Modified (bien); con backend S3
  se usa `StreamingResponse` sin validadores, así que cada expiración de TTL
  re-descarga el cuerpo completo de cada thumbnail de la grid. El frontend ya
  revalida (`cache: "no-cache"` en `getAuthenticatedBlob`) esperando 304s.
- **Evidencia.** `backend/app/api/v1/files.py:220-238` y `:62-85`;
  `frontend/src/lib/api/request.ts:34-46`.
- **Impacto esperado.** En instalaciones S3, una grid de 100 modelos pasa de
  ~100 GETs con cuerpo a ~100 304s por visita (post-primer-load).
- **Complejidad.** Media-baja. Los blobs son inmutables y direccionables por
  contenido; un ETag derivado del `file_id` + key es suficiente.
- **Riesgos.** Reutilización de `file_id` tras un reset de DB — el mismo caso
  que ya motivó el `no-cache` del frontend; usar un componente de contenido
  (p.ej. mtime del objeto o sha) en el ETag lo cubre.
- **Alternativa con infraestructura externa (opcional).** Servir thumbnails S3
  vía `presigned_download_url` (seam `StorageBackend` ya lo expone) y dejar
  que el navegador cachee contra S3/CDN directamente.
- **Pasos.**
  1. Añadir `ETag` en `thumbnail_response` (p.ej. `"{file_id}-{size}"` del stat/HEAD).
  2. Responder 304 cuando `If-None-Match` coincida (mismo patrón que `stl_response`, `files.py:270-278`).
  3. Test HTTP: segunda petición con `If-None-Match` → 304 sin cuerpo.

## 6. Índices compuestos para las consultas calientes de `files`

- **Problema observado.** Las consultas dominantes filtran
  `files(model_id, deleted_at)` y `files(model_id, file_type, deleted_at)`
  (detalle, facetas de la grid, presencia en impresoras). Hoy solo hay índices
  de una columna; SQLite/Postgres usan `model_id` y post-filtran.
- **Evidencia.** `backend/app/db/models.py:198-239` (definición);
  `modules/library/model_views.py:435-514` (consultas).
- **Impacto esperado.** Imperceptible hasta ~10⁴ archivos; a partir de ahí
  evita escaneos secundarios por modelo. Es barato asegurar el futuro.
- **Complejidad.** Baja — **nueva migración Alembic aditiva** (regla dura: no
  tocar migraciones existentes).
- **Riesgos.** Ninguno funcional; coste de escritura marginal.
- **Pasos.** Nueva migración con
  `Index("ix_files_model_live", "model_id", "deleted_at")` y
  `Index("ix_files_model_type", "model_id", "file_type")`; probar
  upgrade-desde-release-anterior con datos (regla del repo).

## 7. `vault_stats`: 8 counts secuenciales

- **Problema observado.** Ocho `SELECT count(...)` independientes por carga
  del dashboard.
- **Evidencia.** `backend/app/modules/library/model_views.py:869-928`.
- **Impacto esperado.** Menor (SQLite local los resuelve en µs); en Postgres
  remoto son 8 round-trips → 2.
- **Complejidad.** Baja: los tres counts sobre `files` colapsan en un
  `GROUP BY file_type` o en agregados condicionales
  (`sum(case when ...)`); los counts de taxonomy/printers pueden unirse con
  subqueries escalares en un solo SELECT.
- **Riesgos.** Legibilidad; mantener los nombres de campos del schema.
- **Pasos.** Reescribir con agregados condicionales + test de igualdad contra
  los valores actuales.

## 8. Verificación JWT duplicada por request

- **Problema observado.** El middleware `bind_audit_context` decodifica el
  bearer token para el actor del audit-log, y `get_current_user` vuelve a
  decodificarlo en la dependencia. Dos verificaciones HMAC + parse por request
  autenticado.
- **Evidencia.** `backend/app/main.py:228-247`; `core/security.py`.
- **Impacto esperado.** Micro (HS256 es barato); es más ruido conceptual que
  coste. Vale la pena solo si se toca esa zona por otro motivo.
- **Solución propuesta.** El middleware guarda el payload verificado en
  `request.state`; la dependencia lo reutiliza si está presente.
- **Riesgos.** Mantener idéntica la semántica de expiración/error entre ambos
  caminos.

## 9. `RateLimiter`: claves inactivas nunca expiran

- **Problema observado.** `_hits` es un `defaultdict(list)` que solo poda los
  timestamps de una clave cuando esa clave vuelve a llamar a `check()`. IPs
  que dejan de llegar quedan en el dict para siempre — crecimiento de memoria
  lento pero sin cota en procesos de meses expuestos a Internet.
- **Evidencia.** `backend/app/core/ratelimit.py:18-38` (el propio módulo marca
  su techo con un comentario `ponytail:` para multi-worker; esto es un techo
  distinto: memoria intra-proceso).
- **Impacto esperado.** Higiene; en un vault doméstico son KB. En un host
  expuesto con escaneo constante, evita un dict de cientos de miles de IPs.
- **Complejidad.** Baja: barrido perezoso (cada N checks, eliminar claves cuyo
  último hit sea más viejo que la ventana).
- **Alternativa con infraestructura externa (opcional).** El comentario del
  módulo ya la nombra: store compartido (Redis) para multi-worker — mantener
  como opción, nunca dependencia dura.
- **Pasos.** Añadir contador de operaciones + purga bajo el lock; test con
  claves envejecidas artificialmente.

## 10. `print_statistics`: agregación en Python

- **Problema observado.** Carga todas las filas de jobs completados de la
  ventana y agrega colecciones/filamentos/buckets en Python.
- **Evidencia.** `backend/app/modules/library/model_views.py:942-1140`.
- **Impacto esperado.** Con miles de prints/año sigue siendo milisegundos; el
  diseño actual (coste congelado en la fila al completar, ver docstring) ya
  eliminó el problema caro. Solo migrar a `GROUP BY` si el dashboard se nota
  lento con historiales muy grandes.
- **Complejidad.** Media (tres agregaciones distintas + bucketing por fecha
  portable SQLite/Postgres). **Riesgos.** Divergencia de redondeos/nulls con
  la versión actual; cubrir con tests de paridad.

## 11. Listados paginados sin total

- **Problema observado.** `GET /models` (y trash) devuelven arrays planos; el
  frontend infiere `hasMore` por `length === pageSize` y muestra
  `models.length` como conteo salvo en la raíz (que usa `vault_stats`). No hay
  forma de mostrar "1–50 de 1.234" en vistas filtradas.
- **Evidencia.** `backend/app/api/v1/models.py:159-177`;
  `frontend/src/lib/queries.ts:150-160`;
  `frontend/src/components/model-grid.tsx:363-366`.
- **Impacto esperado.** Contrato más rico para la UI; coste: un
  `SELECT count(*)` extra por página (con los mismos filtros).
- **Complejidad.** Media — es un cambio de contrato API (envelope
  `{items, total}` o header `X-Total-Count`; el header es retro-compatible y
  no rompe clientes existentes).
- **Riesgos.** Romper consumidores del array plano → preferir el header.
- **Pasos.** Añadir `X-Total-Count` opcional (query param `with_total=true`
  para no pagar el count siempre); consumirlo en `useModelList`.

## 12. `_usage_cache` sin cota

- **Problema observado.** Dict módulo-level keyed por
  `(backend, data_dir)`; cada reconfiguración runtime / test añade una entrada
  que nunca se elimina.
- **Evidencia.** `backend/app/modules/library/model_views.py:848-866`.
- **Impacto esperado.** Insignificante en producción (1–2 claves); es higiene.
- **Pasos.** Cota trivial (limpiar el dict al insertar si supera ~8 entradas)
  o dejarlo documentado como está — coste real ≈ 0. Prioridad mínima; se lista
  por exhaustividad.

---

## Observaciones sin acción propuesta (estado ya sano)

- **Uploads**: streaming a staging con cap de tamaño
  (`api/v1/ingest.py:_stage_upload`, `modules/storage/storage.py:43-47`) — correcto.
- **SQLite**: WAL, `synchronous=NORMAL`, `busy_timeout=5000`,
  `foreign_keys=ON` por conexión (`db/session.py:28-41`) — correcto.
- **N+1 en browse/trash/export**: ya batcheado y documentado como invariante
  (`model_views` docstring) — mantener la disciplina en código nuevo.
- **Notificaciones**: outbox transaccional + dispatcher con backoff y
  circuit-breaker; poll de 15 s solo cuando el master switch está activo —
  razonable. Una migración a `RealtimeBus`/`TaskQueue` (seam existente) solo
  si aparece un requisito de latencia sub-segundo.
- **Observabilidad**: métricas Prometheus con cardinalidad acotada por route
  template, request-id propagado, gauge de impresoras pull-style — sólido.
  Posible añadido barato: histograma de duración de queries lentas (log >100
  ms) para detectar regresiones N+1 en producción.
- **Seguridad**: API keys hasheadas, share tokens hasheados, secretos
  enmascarados en API y redactados en audit diffs, `/metrics` con token
  opcional, escaping de LIKE en el boundary RBAC (`rbac.py:_like_prefix`).
  Pendiente conocido del roadmap 0.8.5 (X-Forwarded-For para el rate limiter
  detrás de proxy) — ya está trackeado en el plan, no se duplica aquí.
