# Imagen reproducible

Dockerfile multicomponente único con Python 3.12.12-slim-bookworm fijado por digest,
dependencias fijadas en requirements-node/documents, usuario 10001:10001,
HEALTHCHECK /healthz y entrada `python -B -m deployment.cluster`.
La base exacta y digest final están en IMAGE_VERIFIED.json y el workflow tfi-image.yml.

Variables: TFI_REPLICAS, TFI_DIFFICULTY, TFI_DIFFICULTY_MODE, TFI_EXPERIMENT;
HOSTNAME identifica el pod. `/data` debe ser volumen independiente por nodo;
`/config/actors.json` es configuración sintética; `/run/hisjb/credentials.json` es
un secreto efímero externo al código. No ejecutar el contenedor sin esos archivos.
Los puertos internos no deben publicarse indiscriminadamente.

La prueba de contenedor 41876907701 ejecutó el recorrido real y reinicio con datos
persistentes; sus doce capturas son de Chromium en runner, no de GKE ni Edge.
La publicación OIDC 41886329974 construyó exclusivamente HISJB y verificó el digest.
No se repitieron builds para las correcciones de DNS/Helm o etiquetas de consola.
