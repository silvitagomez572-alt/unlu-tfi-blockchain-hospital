# Diagnóstico multinodo GKE - 04/11/2026

Los pods reales se llaman `hisjb-0`, `hisjb-1` y `hisjb-2`; no `pow-*`.
El motor de consenso y sus límites de validación no se modificaron.

## Hallazgos verificados

1. Service `hisjb-headless`, ClusterIP None, selector `app=hisjb`, puerto TCP
   19980. `/healthz`, `/readyz` y `/metrics` usan ese mismo puerto. EndpointSlices
   contenían los tres pods. `publishNotReadyAddresses=true` permite descubrirlos
   antes de Ready; un endpoint anunciado no acredita readiness.
2. Los nombres FQDN de peers coinciden con el StatefulSet y namespace
   `tfi-hospital`. La API respondía por IP directa entre pods.
3. DNS UDP contra el Service 10.74.0.10 vencía a los dos segundos. La misma pregunta
   dirigida al endpoint kube-dns 10.73.0.6 respondió en menos de un milisegundo.
   El nombre propio se resolvía mediante `/etc/hosts`; no era prueba del DNS de peers.
4. Se conservó la política restrictiva y se agregó sólo 10.74.0.10/32 TCP/UDP 53.
   La consulta al Service respondió luego en 0,000375 s. No se abrió egress global.
5. La actualización mezclaba el perfil anterior (un nodo/dificultad 3) con el nuevo
   (tres nodos/dificultad 1). Readiness exige sincronización válida: no se eliminó
   esa condición ni se alargaron timeouts para forzar éxito.
6. Se usó OnDelete y reemplazo controlado de pods con revisión obsoleta, manteniendo
   PVC y directorios de cada experimento. La transición inicial requirió retirar
   explícitamente el campo RollingUpdate del objeto; el dry-run del servidor pasó.
   Este método admite interrupción temporal en el laboratorio; no se presenta como
   actualización de producción sin downtime.
7. Después de corregirlo, tres pods Ready y los escenarios de carga comenzaron a
   validar propagación, inclusión y cadenas completas iguales. El resultado de
   cada celda está en `MATRIZ_EXPERIMENTAL.csv`, sin extrapolar a celdas no ejecutadas.

## Clasificación de fallos

- `gaierror`/DNS timeout: conectividad DNS del Service antes de la corrección.
- `ConnectTimeout`: consecuencia observada en consultas P2P sin resolución útil.
- `connection refused` de startup probes: arranque del proceso, documentado en eventos.
- Readiness HTTP 503: no estar sincronizado; distinto del 503 de carga.
- HTTP 503 `Service Unavailable` bajo 50/101 solicitudes: límite Uvicorn de 32
  conexiones/tareas concurrentes. El límite se conservó; no significa bloque inválido.
- Conflictos 409 y validación 422 se contabilizan aparte si aparecen.
- Credencial Kubernetes vencida: fallo de una consulta del operador, sin prueba de
  pérdida de transacciones ni cambio del motor. Se renovó la sesión temporal.

Fuentes originales: `evidence/phase4/gke-runtime-20261104/`:
`dns-transport-before.stdout.txt`, `dns-after-policy.stdout.txt`,
`node1-readiness-diagnostic.stdout.txt`, `headless-service-diagnostic.stdout.txt`,
`headless-endpointslices.stdout.txt`, `strategy-dry-run.stdout.txt`,
`verified-profile-n3-d1.stdout.txt` y resultados `cell-*.json`.
