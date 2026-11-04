# Infraestructura como código

La consigna permite Terraform u OpenTofu. Se usó Terraform 1.14.9 con provider
hashicorp/google 5.45.2; no se presenta OpenTofu como ejecutado.
Bootstrap: APIs, presupuesto, Artifact Registry, OIDC y permisos restringidos.
Runtime: red, subred, cuenta de nodo, permisos mínimos y clúster temporal.
El proyecto está validado por igualdad exacta; no admite otro ID.

Validación previa: fmt -check, init -backend=false y validate; Helm lint/template y
actionlint. Plan revisado antes de aplicar. El estado Terraform permanece privado.
No se incluyen estados ni planes binarios en el ZIP. El entorno de autenticación
usa sesión temporal del SDK y OIDC sin claves JSON permanentes.

La configuración final explicita monitoring_config vacío y managed_prometheus=false;
el cambio se verificó mediante operación DONE. La observabilidad de esta prueba se
ejecutó dentro de la VM ya prevista, con exportación antes de destruir el clúster.
