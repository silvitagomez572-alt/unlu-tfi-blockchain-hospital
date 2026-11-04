# Helm y persistencia

Chart: `infrastructure/helm/hisjb`. Valores: digest inmutable de imagen, replicas
1/3/5, dificultad 1/2/3 y perfil experimental. StatefulSet `hisjb`, Service
`hisjb-headless`, PVC independientes `data-hisjb-0` a `data-hisjb-4`.
Se validaron lint y template y se aplicó el chart en GKE. Readiness `/readyz` exige
estado sincronizado/aislado; liveness `/healthz` comprueba el proceso.

No copiar el digest o namespace de otro laboratorio. El Service publica direcciones
antes de Ready para descubrimiento P2P; eso no convierte un pod no saludable en Ready.
NetworkPolicy permite aplicación y DNS necesarios, incluyendo DNS Service /32 53.
El mecanismo OnDelete coordina reemplazos al cambiar parámetros consensuados;
acepta downtime temporal de laboratorio y conserva el PVC. No es un rollout HA.

La consola GKE se monta mediante ConfigMap con checksum para distinguir entorno,
proyecto, namespace y nodo real. La imagen del motor permanece idéntica.
