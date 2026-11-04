# API implementada y consola local

Perfil documental: `documents/app.py`, que extiende `node/app.py`; esquemas en
`node/schemas/__init__.py`. Fecha: 04/11/2026. Los ejemplos siguientes describen
contratos, **no son transcripciones de ejecuciones ni hashes observados**.
La evidencia HTTP está en `evidence/phase3/tests/`.

## Reglas comunes

Base local: `http://127.0.0.1:19980`. JSON estricto, sin campos extras; cuerpo máximo
64 KiB y recepción máxima 3 s. UUIDv4 canónicos, hashes hexadecimales de 64 caracteres.
Las rutas de datos exigen Bearer de rol; no copiar tokens en ejemplos, archivos o
capturas. Errores comunes: 401 sin credencial, 403 permiso denegado, 408 cuerpo lento,
413 tamaño, 422 esquema/protocolo inválido, 429 límite y 503 almacenamiento/presupuesto.
El JSON de error usa `detail`; no devuelve el cuerpo rechazado.

`T` designa una transacción completa: network_hash, document_id, version_id,
document_hash, event_type, timestamp, actor_id, previous_version_id,
previous_document_hash y tx_id. Los dos anteriores pueden ser null al iniciar.
`B` designa un bloque: index, previous_hash, transactions (lista T), timestamp,
difficulty, network_hash, nonce y hash. No enviar literales `T`/`B`: usar los objetos
válidos recuperados de la API o construidos por el protocolo.

## Nodo y P2P

| Método y ruta | Entrada y validaciones | Respuesta correcta | Otros estados / ejemplo |
|---|---|---|---|
| GET `/healthz` | Sin cuerpo; público local | 200 `{status:"ok",node_id,pid}` | 503 si estado no saludable. Consulta de liveness, no consenso. |
| GET `/readyz` | Sin cuerpo; público local | Estado de sync; 200 para synced/isolated | 503 para otros estados; isolated no significa peers disponibles. |
| GET `/metrics` | Sin cuerpo; público local | 200 texto Prometheus | `pow_block_height`, `pow_mempool_transactions`, duración y errores; no JSON. |
| GET `/chain` | Rol o peer | 200 `{node_id,network_hash,tip,cumulative_work,blocks:[B]}` | Cadena completa, sin paginación actualmente. |
| GET `/blocks/{index}` | Rol, índice entero 0..100000 | 200 B | 404 ausente, 422 índice. Ejemplo: `/blocks/0`. |
| POST `/transactions` | Solo peer; T, hash/UUID/timestamp válidos; X-TFI-Hops 0..3 | 202 `{tx_id,status:"pending"}` | 409 duplicado/conflicto; validar política antes de persistir. |
| GET `/transactions/pending` | Rol o peer; sin cuerpo | 200 `[T]` | Vacío `[]` significa sin pendientes, no fallo. |
| GET `/peers` | Rol; sin cuerpo | 200 `{node_id,peers,sync}` | Lista vacía permitida. |
| POST `/peers/sync` | Solo operator; sin cuerpo | Resumen real de sincronización | Un fallo de peer puede quedar registrado en el resumen; HTTP 200 no prueba convergencia. |
| POST `/mine` | Solo operator; sin cuerpo | 200 `{block:B,elapsed_seconds,attempts}` | 409 ocupado/tip obsoleto; 503 presupuesto agotado. Tiempo e intentos medidos por motor. |
| POST `/peers/blocks` | Solo peer; B; X-TFI-Hops 0..3 | 200 `{adopted:true|false}` | 422 inválido; no deducir aceptación solo del 200. |

## Documentos y versiones

Entrada sintética para POST `/documents/register` (rol mesa):

```json
{"document_id":"00000000-0000-4000-8000-000000000001","version_id":"00000000-0000-4000-8000-000000000002","fixture_id":1,"metadata":{"schema":"synthetic-circuit-v1","synthetic":true}}
```

Fixture entero 1..10000. La API calcula hash, actor y timestamp; no acepta una historia
clínica ni un actor arbitrario. Responde 202 con transaction_id, campos documentales,
metadata derivada y `status:"pending"`. Documento ya existente: 409.

POST `/documents/versions` usa el mismo JSON más `previous_version_id` y
`previous_version_hash` recuperados del historial. Requiere entrega confirmada de
la versión anterior, UUID nuevo y parentesco coincidente. 202 pendiente, 404 padre
ausente, 409 conflicto/orden y 422 esquema.

POST `/documents/events` recibe:

```json
{"document_id":"00000000-0000-4000-8000-000000000001","version_id":"00000000-0000-4000-8000-000000000002","event_type":"DIRECTION_REVIEWED"}
```

Rol direccion para DIRECTION_REVIEWED, legal para LEGAL_REVIEWED, bio para
VERSION_PREPARED/DELIVERY_RECORDED. 202 con transacción pendiente, 403 rol,
404 documento, 409 etapa/versión/pendiente y 422 esquema. QR_IDENTIFIER_ISSUED solo
se genera con `/qr/create`; minar entre etapas.

GET `/documents/{document_id}/history`: rol humano, UUIDv4, sin cuerpo. Devuelve
200 lista de eventos confirmados, cada uno con `block`, `block_hash` y campos
documentales; 404 sin documento y 422 UUID. No incluye pendientes.

POST `/documents/verify`: rol humano; recibe document_id, version_id y document_hash
SHA-256 obtenido del fixture. Devuelve 200 con `integrity`, `registrations`,
`hash_presented`, `hash_calculated:null`, `hash_registered`, `hash_method` y `height`.
El servidor compara el hash presentado; no ha recibido ni calculado un archivo
arbitrario. MATCH, MISMATCH, NOT_FOUND y CONFLICT son resultados de dominio, no
códigos HTTP. La política documental impide normalmente admitir cadenas conflictivas.

## QR temporal

| Método y ruta | Entrada | Salida / validación |
|---|---|---|
| POST `/qr/create` | Rol bio; document_id, version_id, ttl_seconds 60..3600 (300 por defecto), max_uses 1..10 (1 por defecto) | 202 con grant_id, token, timestamps, usos, url, qr_svg, transaction_id y pending_confirmation. 409 si preparación no confirmada o existe pendiente. Token secreto: no registrar la respuesta completa. |
| GET `/qr/{token}` | Rol humano; token efímero válido | 200 `{verification,uses,remaining_uses,expires_at}`. Consume un uso. 403 si expiró, fue revocado, está agotado o emisión no confirmada; 503 fallo del registro. |
| POST `/qr/{token}/revoke` | Rol bio; sin cuerpo | 204 sin cuerpo; 403 token no disponible. Revocación persiste localmente. |

Ejemplo de emisión: mismos UUID sintéticos, `ttl_seconds:300,max_uses:2`. La respuesta
real contiene un secreto; el ejemplo deliberadamente no incluye un token utilizable.
La URL es local al nodo emisor y requiere autenticación: un escaneo externo por sí
solo no entrega acceso público ni demuestra una DApp remota.

## Consola del navegador

GET `/console/` entrega HTML y cookie HttpOnly. GET `/console` redirige. GET
`/console/assets/{name}` admite solo app.js y style.css. Host debe coincidir con
127.0.0.1:puerto. Las siguientes rutas requieren cookie y X-HISJB-CSRF; POST JSON,
Origin exacto y límite 240 solicitudes/minuto. Sin CORS abierto.

| Ruta | Parámetros/cuerpo | Salida |
|---|---|---|
| GET `/console/api/summary` | Ninguno | Estado real: altura, contadores, pendientes, bloques, dificultad, actores, minería y sampled_at. |
| GET `/console/api/nodes` | Ninguno | nodes y same_tip; peers limitados a la configuración, respuesta máxima 4 MiB y timeout 1 s. |
| GET `/console/api/fixture/{number}` | Número 1..10000 | fixture_id, synthetic_content y document_hash. |
| GET `/console/api/block/{number}` | Índice | B de `/blocks/{index}`, mismos errores. |
| GET `/console/api/history/{document_id}` | UUID | Historial real, mismos errores. |
| POST `/console/api/command` | action, role y payload | Respuesta de la ruta real, conservando su código HTTP. |

Ejemplo contractual de comando: `{"action":"mine","role":"operator","payload":{}}`.
Acciones: register, version, event, mine, sync, verify, qr_create, qr_read y qr_revoke.
Las dos últimas reciben token en payload; el adaptador construye la ruta validada.
La selección de rol pertenece a una demo local, no demuestra autenticación hospitalaria.

Los nueve casos nuevos de mensajes de conexión están preparados pero bloqueados
por el preflight de memoria. No se afirman como pruebas de Edge aprobadas.
