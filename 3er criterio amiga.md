Confirmé en el repo del proyecto que FreeLLMAPI ya habla el formato Anthropic Messages directamente para que Claude Code y los SDKs oficiales de Anthropic funcionen contra su pool, e implementa la Responses API que las versiones actuales de Codex CLI requieren como una capa traductora sobre el mismo router. Y, clave para ti: acepta un "custom provider" que apunte a cualquier endpoint OpenAI-compatible — llama.cpp, LM Studio, vLLM, Ollama local o un gateway remoto — configurado desde su página de Keys. Eso es literalmente lo que ya expone tu bridge (Chat Completions OpenAI-compatible). 
github
github

El botón "Configuración automática" de tu captura (npx freellmapi setup-claude, setup-codex) escribe por sí solo la config de cada herramienta apuntando a FreeLLMAPI, respaldando lo que ya existía sin sobreescribirlo a ciegas. No es algo que tengas que replicar: en cuanto registres tu AGY Model Bridge como custom provider en Keys, esa misma pantalla pasa a ser tu Etapa B funcionando, no una funcionalidad ajena que copiar. 
github

Un matiz que tu Notion todavía no cubre

Claude Code y Codex no hablan el mismo protocolo, y esto ya lo confirmé por fuera de FreeLLMAPI, en documentación independiente: Claude Code usa el contrato Messages de Anthropic mientras que los custom providers de Codex usan el contrato Responses de OpenAI, y no son intercambiables. Además, para Claude Code la URL no lleva /v1 porque el propio cliente añade la ruta de Messages, mientras que Codex sí necesita el /v1 en su Base URL. Mira tu propia captura: BASE_URL=http://127.0.0.1:31415 para Claude Code (sin /v1) vs .../31415/v1 para Codex. No es un detalle estético del diseño de FreeLLMAPI — es la firma de esa diferencia de protocolo. 
dev
dev

La buena noticia: esa traducción (Anthropic Messages ↔ Responses ↔ Chat Completions) es trabajo de FreeLLMAPI, no de tu bridge. Tu bridge solo necesita seguir devolviendo Chat Completions correcto. Pero no lo des por probado hasta verlo: cuando lo conectes, valida los tres flujos por separado (Claude Code, Codex no-stream, Codex stream) — que funcione con curl directo a tu bridge no garantiza que funcione a través de la traducción de FreeLLMAPI.

El concepto que buscas

Se llama LLM Gateway (o AI Gateway / Model Gateway): un punto único que absorbe la diversidad de protocolos de distintos backends y expone una interfaz uniforme a los clientes, con la comodidad extra de auto-configurarlos. FreeLLMAPI, Ollama, LiteLLM, OpenRouter y Portkey están todos en esa categoría — no es casualidad que FreeLLMAPI le llame "pasarela" en su propia UI.

Si quieres el nombre a nivel de patrón, con tu vocabulario de hexagonal/DDD: tu bridge es un Adapter / Anti-Corruption Layer (aísla a Claude Code y Codex del protocolo propietario de Cloud Code Assist). FreeLLMAPI es el Gateway que agrupa muchos adapters como el tuyo detrás de una sola puerta.

Camino 1 — Dárselo a FreeLLMAPI

Aquí casi no hay construcción, es configuración, no código nuevo:

Registras tu AGY Model Bridge como custom provider en el panel de Keys de FreeLLMAPI (base_url → tu bridge local, api_key → la que ya generaste).
Corres npx freellmapi setup-claude --url ... / setup-codex --url ... tal cual salen en tu captura, apuntando al puerto local de FreeLLMAPI (el 31415 de la imagen).
FreeLLMAPI se encarga de la traducción Anthropic Messages / OpenAI Responses. Tu bridge solo necesita seguir hablando Chat Completions bien.

Esto es literalmente tu Etapa B ya diseñada en el documento. Nada que definir aquí.

Camino 2 — Hacerlo tú mismo, sin FreeLLMAPI en el medio

Aquí sí construyes dos piezas nuevas, distintas entre sí:

Pieza 1 — Shims de protocolo (la parte dura)
Tu bridge hoy solo habla Chat Completions. Para que Claude Code y Codex le hablen directamente, sin FreeLLMAPI traduciendo, necesitas añadir dos fachadas de protocolo delante de tu lógica actual:

Un shim Anthropic Messages (POST /v1/messages) para Claude Code — traduce el formato de mensajes/eventos SSE de Anthropic hacia lo que tu bridge ya sabe generar.
Un shim OpenAI Responses (POST /v1/responses) para Codex — mismo principio, distinto formato de eventos.

Uso el término "shim" a propósito: es el mismo que usa FreeLLMAPI para describir su propia capa de traducción de Responses API. Es decir: si haces esto, estás reconstruyendo dentro de tu proyecto una porción de lo que FreeLLMAPI ya resuelve.

Pieza 2 — Provisioner de configuración (la parte mecánica)
Un script/CLI propio, sin servidor, que se ejecuta una vez y escribe la config local de cada herramienta apuntando a tu bridge:

Para Claude Code: setea ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN (o edita su settings.json), sin el sufijo /v1 — el cliente ya lo agrega.
Para Codex: edita ~/.codex/config.toml, agregando un bloque [model_providers.tu_nombre] con base_url, env_key y wire_api = "responses".

No hay un nombre estandarizado en la industria para esto — funcionalmente es un instalador/configurador de clientes; es exactamente lo que hacen setup-claude/setup-codex de FreeLLMAPI, solo que apuntando a tu bridge en vez de a ellos.

El "thinking" de Gemini se va a comer tu respuesta si no lo fijas explícitamente

Mira tus propios números, ya los tienes documentados: sección 14.6, totalTokenCount: 37 con thoughtsTokenCount: 29 (79% del presupuesto en razonamiento invisible); en la subpágina, totalTokenCount: 86 con thoughtsTokenCount: 75 (87%). No es ruido puntual, es el comportamiento default de los modelos "thinking" de Gemini.

Confirmé en la documentación oficial que generationConfig.thinkingConfig acepta un campo thinkingBudget, donde un valor de 0 desactiva el razonamiento y -1 activa un presupuesto dinámico que el modelo ajusta según la complejidad, y que el schema completo de generationConfig incluye tanto thinkingBudget como un campo hermano thinkingLevel dentro de thinkingConfig — este último es el que probablemente aplica a tus modelos Gemini 3 (gemini-3.1-pro-high/low, gemini-3.6-flash-high/low/medium), donde el nivel ya viene sugerido en el propio nombre del modelo. 
google
google

Por qué importa ahora y no como ajuste posterior: en Card 1 (FreeLLMAPI, rotación) esto es tolerable — si un proveedor responde vacío, el router prueba otro. En Cards 2/3 no hay a quién rotar: si no fijas thinkingBudget/thinkingLevel explícito por request desde el día uno, Claude Code y Codex van a recibir respuestas truncadas o vacías de forma intermitente, y desde el arnés eso se lee como "el modelo está roto", no como un parámetro sin setear.

3. La pregunta que decide si Cards 2/3 pueden ser standalone de verdad

Tu credencial en Keychain trae access_token + refresh_token, pero un refresh_token de Google solo sirve junto con el client_id/client_secret de la app que lo emitió — que están embebidos en el binario de AGY, no en el token. Dos escenarios, y son dos arquitecturas distintas:

Si extraes esas credenciales del binario: tu bridge refresca por su cuenta, sin depender de AGY corriendo. Standalone real.
Si no las tienes: solo puedes leer el token que AGY ya refrescó en segundo plano mientras esté abierto. "Uso local standalone" sería entonces una ilusión — cuando el access_token expire con AGY cerrado, las 3 tarjetas caen juntas con 401 sin aviso.

Decide esto antes de escribir el código de refresh, porque no es lo mismo un OAuth client completo que un simple "leer Keychain y fallar con mensaje claro si expiró".

4. Un solo proceso detrás de las 3 tarjetas, no tres compitiendo por el mismo token

Con las 3 tarjetas activas tienes 3 consumidores concurrentes de la misma cuenta/proyecto (aicode-consumers). Si cada tarjeta levanta su propio proceso leyendo Keychain por separado, te expones a condiciones de carrera y a rate limiting que no vas a poder diagnosticar (¿gastó cuota Codex, o FreeLLMAPI rotando hacia tu provider en paralelo?). Un solo daemon local, tres namespaces de ruta (/v1/chat/completions, /v1/messages, /v1/responses) sobre un único caché de token y un único limitador de tasa. Tres tarjetas en la UI, un proceso debajo.

5. Decide si tu provider entra en la rotación automática de FreeLLMAPI o no

Si registras el bridge como custom provider sin marcarlo como uso puntual, FreeLLMAPI puede elegirlo automáticamente como parte de la rotación de Card 1 — consumiendo la cuota que querías reservada para cuando uses Cards 2/3 a propósito. Revisa si el panel de Keys tiene una opción de prioridad/manual-only; si no la tiene, usa dos API keys de bridge distintas (mismo proceso, distinto consumo medible) para no mezclar ambos usos en las métricas.

Lo que encontré en el repo oficial de NousResearch/hermes-agent y en su documentación pública:

El esquema real de custom_providers en ~/.hermes/config.yaml incluye un campo api_mode, y todos los ejemplos oficiales que encontré (documentación de Hermes, integraciones de terceros como HPC-AI) usan api_mode: chat_completions, apuntando a endpoints explícitamente OpenAI-compatibles — vLLM, SGLang, OpenRouter, SiliconFlow.
El propio README del proyecto lo dice sin ambigüedad: la vía de "custom endpoint" está pensada para VLLM, SGLang, "cualquier API OpenAI-compatible" — no para el formato Messages de Anthropic.

Eso coincide EXACTO con tu captura: BASE_URL=http://127.0.0.1:31415/v1, con /v1, igual que la tarjeta de Codex — no igual que la de Claude Code (que no lo lleva).

terminas construyendo los mismos 2 shims que ya tenías planeados, pero ahora sabes que uno de ellos (Anthropic Messages) solo lo necesita Claude Code, no Claude Code + Hermes. Hermes se resuelve con la tarjeta que ya tienes funcionando para Card 1 — solo cambia a quién apunta el BASE_URL.

Una cosa que sí me queda pendiente de verificar y no voy a fingir que ya lo sé: si api_mode de Hermes admite algún valor tipo anthropic que Requesty esté usando por alguna razón que no encontré documentada. Si te importa exprimir el prompt caching de Anthropic específicamente para Hermes, vale la pena que revises tú mismo el código fuente de hermes_cli/config.py (el archivo que apareció en los issues que encontré) para ver los valores válidos reales de ese campo
