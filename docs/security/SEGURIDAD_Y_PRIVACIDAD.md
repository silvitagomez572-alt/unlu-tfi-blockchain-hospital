# Seguridad y privacidad del prototipo

Estado al 04/11/2026: controles locales implementados; no seguridad hospitalaria
certificada ni servicio apto para datos clínicos reales.

- Se admiten fixtures sintéticos numerados; el servidor calcula su SHA-256. No se
  reciben documentos clínicos ni texto libre. UUID, versión, hash, evento, actor
  simulado y timestamp forman el registro. Los bytes documentales no se guardan
  en la blockchain; la demo puede reconstruir únicamente sus fixtures conocidos.
- SHA-256 permite detectar diferencias respecto de un hash registrado. No acredita
  autoría, verdad del contenido, titularidad, firma digital ni cadena de custodia legal.
- Un hash y un seudónimo no anonimizan automáticamente: pueden vincularse eventos,
  horarios y hashes conocidos. No trasladar estas reglas directamente a datos reales.
- La API documental exige roles mediante credenciales efímeras. Los peers reciben
  permisos de intercambio limitados. El modelo confía en esos peers autorizados;
  todavía no hay firmas Ed25519 ni identidad institucional.
- La consola es un modo de operador local: puede seleccionar roles simulados.
  No equivale a un sistema multiusuario hospitalario. El navegador no recibe las
  credenciales internas de rol. Usa cookie HttpOnly/SameSite Strict, CSRF,
  Host/Origin exactos y rutas permitidas. Bind local en 127.0.0.1; dentro del pod GKE la API escucha en 0.0.0.0:19980, protegida por NetworkPolicy. La consola sólo se accede mediante túnel localhost autenticado.
- No se agrega CORS abierto para corregir fallos de conexión. Una API apagada
  requiere recuperar capacidad y el proceso; una sesión vencida requiere recarga.
- El QR lleva un token temporal. SQLite conserva su SHA-256, expiración, usos y
  revocación. La consulta requiere además acceso autenticado y evento de emisión
  confirmado. No capturar tokens/QR activos; revocar antes de guardar evidencia.
  La revocación no retira copias previas ni vuelve privada la cadena compartida.
- El registro QR es del nodo emisor, no un registro distribuido. Escanear su URL
  desde otro dispositivo no constituye una DApp remota funcional: apunta a localhost
  y requiere autenticación adicional.
- El snapshot y su checksum detectan corrupción accidental; no impiden que quien
  controla completamente el disco reescriba ambos. La validación independiente y
  los peers son necesarios para comprobar el contenido, no solo el checksum.
- Claves, cookies y tokens no deben entrar en Git, logs, ZIP o capturas. No incluir
  `.runtime`, `node-data` ni bases QR operativas en el paquete de entrega.

## Modelo de confianza y alternativa convencional

Mesa de Entrada registra, Dirección y Legales intervienen, Bioestadística prepara
y entrega; son roles simulados de un circuito informado por la estudiante. Los
verificadores contrastan hashes y orden de eventos. Una blockchain puede aportar
validación independiente cuando varias partes administran nodos y discrepan sobre
el historial. Con todos los nodos bajo una sola administradora, esa independencia
es limitada: una base de datos con auditoría, permisos y respaldos podría resolver
la necesidad con menor complejidad. PoW educativo no reemplaza esos controles.

## Pendientes

Autenticación institucional, TLS, autorización sobre documentos, manejo distribuido
de QR, auditoría durable correlacionada y revisión de amenazas. Docker sin root, IAM mínimo, OIDC y políticas GKE del TFI se ejecutaron y verificaron en el entorno temporal. No reutilizar como
evidencia propia los permisos o infraestructura del Lab 8.
