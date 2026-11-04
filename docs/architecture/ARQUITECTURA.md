# Arquitectura comprobada de HISJB

Una consola estática del mismo origen utiliza sesión, CSRF y operaciones cerradas
del adaptador ASGI; éste llama la API documental FastAPI real. Cada nodo dispone de
cadena, mempool, identidad, lista de peers, locks y persistencia independientes.
Los documentos son fixtures sintéticos externos al bloque; dentro se guardan hash,
identificadores seudónimos, versión, evento, actor simulado y timestamp.

## API, almacenamiento y procesamiento

API de recepción no equivale a nodo: es la interfaz del nodo. Un HTTP 202 admite
una transacción pendiente; su confirmación requiere inclusión en un bloque válido.
El snapshot JSON conserva cadena y mempool juntos con checksum, escritura temporal,
fsync y reemplazo atómico. SQLite guarda los accesos QR locales con hash del token.
El hilo de minería por nodo ejecuta PoW con lock, intentos y tiempo acotados; no es
un worker independiente ni una cola compartida por múltiples APIs.

El motor valida cadenas completas antes de adoptar mayor trabajo acumulado; en un
empate aplica orden lexicográfico del hash final. Se propagan transacciones y bloques
y se sincronizan peers. La matriz GKE compara las cadenas completas, no sólo alturas.

## Despliegue real

GKE zonal us-central1-a, una VM e2-standard-4, 1/3/5 pods, cinco PVC de 10 GiB como
máximo. Service headless y DNS estable, NetworkPolicy y puerto HTTP/métricas 19980.
La consola se accedió exclusivamente por túnel autenticado con escucha localhost.
Prometheus y Grafana compartieron un pod temporal con datos en emptyDir exportados.
No hubo balanceador público ni segundo clúster.

Se corrigió DNS del Service mediante una regla exacta /32 TCP/UDP53 y los cambios
de perfil se hicieron coordinadamente con OnDelete, conservando PVC. No se retiró
readiness ni se aumentaron timeouts para simular salud. Los perfiles experimentales
usan subdirectorios de estado distintos; la demo original quedó preservada.

## Límites

Los nodos comparten una sola máquina y administración. Esto prueba independencia
lógica y convergencia, no tolerancia a la pérdida del único host ni descentralización
institucional. La política documental exige pasos confirmados y reenvío ordenado tras
reorganizaciones. QR no es estado consensuado. El historial confirmado es durable;
el último tiempo de minería de la UI y algunos contadores reinician con el proceso.
