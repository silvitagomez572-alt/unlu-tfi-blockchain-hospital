# HISJB Evidence Chain - TFI UNLu

Silvia Andrea Gómez Villagra · Modalidad individual · Actualización 04/11/2026.
Prototipo educativo de trazabilidad documental con datos exclusivamente sintéticos.

## Resultado comprobado

Se ejecutó realmente en Google Kubernetes Engine, proyecto exclusivo
`unlu-tfi-hisjb-20261104`, clúster temporal `hisjb-tfi-temp`, namespace `tfi-hospital`.
Una VM e2-standard-4 alojó de uno a cinco nodos blockchain independientes, cada uno
con FastAPI, un hilo minero y un PVC. No son cinco máquinas ni cinco operadores independientes.
Matriz obligatoria: 36 PASS de 36 ejecutados / 36 previstos. Limpieza: PASS.

La consola mostró transacciones reales, minería, bloques, coincidencia SHA-256,
alteración detectada, historial y QR revocado. La persistencia sobrevivió a recrear
`hisjb-0`: cambió el UID del pod, se conservó el UID del PVC y el estado fue idéntico.
Prometheus registró hasta cinco targets UP. Grafana se ejecutó en el mismo GKE.
Las capturas existentes son originales; las faltantes no se sustituyen por imágenes fabricadas.

## Reproducibilidad

- Motor y API: `blockchain/`, `node/`, `documents/`; consola `webconsole/`.
- Entrada de contenedor: `python -B -m deployment.cluster`; puerto interno 19980.
- Docker: `Dockerfile`, dependencias fijadas, usuario 10001, healthcheck.
- Helm: `infrastructure/helm/hisjb`; StatefulSet, headless Service, PVC y NetworkPolicy.
- IaC: `infrastructure/opentofu/`; ejecución comprobada con Terraform 1.14.9.
- CI/OIDC: `.github/workflows/tfi-image.yml`; la publicación real fue la corrida 41886329974.
- Especificación de rutas: `docs/api/ENDPOINTS.md`.
- Datos medidos: `MATRIZ_EXPERIMENTAL.csv`, resultados JSON y logs en `evidence/phase4/`.

La imagen deriva de `681343963bb0315f68ddd1e49855e1a8460eeb25`, con digest
`sha256:0d78467787e7d20d8b648a3b3887a5d848e880607a0f4296247343fe0377230a`.
La identificación GKE de la consola y correcciones de Helm se aplicaron mediante
ConfigMap/configuración, sin alterar el motor ni reconstruir esa imagen.

## Demostración local

Con Python 3.12, dependencias y al menos 1 GiB disponible:

```powershell
python -B tools/serve_hisjb_demo.py --port 19980 --minutes 60
```

Abrir `http://127.0.0.1:19980/console/`. Este supervisor mantiene los límites de RAM,
sesión, Host/Origin y CSRF. Una URL documentada no implica que el servidor siga encendido.
No repetir ensayos aprobados para abrir la aplicación. No aplicar IaC automáticamente:
revalidar identidad del proyecto, permisos, cuota, plan y presupuesto.

## Procedencia y límites

Conservé el template `dpetrocelli/infra-cloud-template` en `reference/lab8/`,
referencia `d4b159c57e208a8a433ff6ac97b3b94098518aa0`; no modifiqué Lab 8.
Las cadenas del TFI tienen formato y reglas propios; no se reutilizan silenciosamente
estados de Lab 8. Consenso: trabajo acumulado verificable y desempate lexicográfico.
Los 35 tests de núcleo, 11 de API y A/B anteriores no se repitieron durante GKE.

No hay granja de workers separada de las APIs. La matriz activa un minero por celda;
los demás nodos validan y sincronizan. QR usa SQLite por nodo y no se replica por consenso.
Los roles son simulados; no se afirma firma digital, validez judicial ni cumplimiento automático.
La trazabilidad completa de rechazos con correlación durable requiere trabajo adicional.
La consigna original conservada del 01/11 exige 1,3,5 nodos; tres dificultades;
concurrencia 1,2,5,10. Las pruebas 50/101 son estrés adicional.

Consigna vigente conservada: propuesta 10/11/2026 y entrega final 20/12/2026.
La fecha personal de cierre solicitada es 06/11/2026. Consultar checklist y PDF para
los límites académicos; no confundir ejecución técnica con una aceptación de la cátedra.
