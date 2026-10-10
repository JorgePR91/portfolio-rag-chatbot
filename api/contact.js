/**
 * POST /api/contact — formulario de contacto del portfolio.
 *
 * Recibe los datos del formulario del frontend, los valida y los reenvía por
 * correo con Resend. Es la única función Node del proyecto (el resto, en api/,
 * son funciones Python de Vercel).
 *
 * Variables de entorno:
 *   RESEND_API_KEY                  clave de Resend
 *   CONTACT_FROM                    remitente, p. ej. "Portfolio <onboarding@resend.dev>"
 *   CONTACT_TO                      buzón donde se reciben las solicitudes
 *   ALLOWED_ORIGINS                 orígenes CORS permitidos, separados por comas
 *   UPSTASH_REDIS_REST_URL / _TOKEN para el límite de peticiones
 */
import { Resend } from "resend";
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";

const resend = new Resend(process.env.RESEND_API_KEY);

const origenesPermitidos = (process.env.ALLOWED_ORIGINS ?? "http://localhost:4200")
  .split(",")
  .map((origen) => origen.trim())
  .filter(Boolean);

// 3 envíos cada 10 minutos por IP: suficiente para una persona real y evita
// que un script agote la cuota gratuita de Resend o llene el buzón de spam.
const limitador = new Ratelimit({
  redis: Redis.fromEnv(),
  limiter: Ratelimit.fixedWindow(3, "10 m"),
  prefix: "ratelimit:contact",
});

const MAX_LONGITUD = { nombre: 100, correo: 254, telefono: 30, mensaje: 4000 };
const EMAIL_VALIDO = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Los datos del visitante acaban dentro del HTML del correo: sin escapar,
// alguien podría inyectar enlaces o etiquetas en el mensaje que se recibe.
function escaparHtml(valor) {
  return String(valor)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function permitido(ip) {
  try {
    const { success } = await limitador.limit(ip);
    return success;
  } catch (error) {
    // Fail-open: si Redis no responde, el formulario sigue funcionando.
    console.error("[ratelimit] Redis no disponible, se deja pasar:", error.name);
    return true;
  }
}

export default async function handler(req, res) {
  // 1. CORS: solo el frontend del portfolio puede llamar desde el navegador.
  const origen = req.headers.origin;
  if (origenesPermitidos.includes(origen)) {
    res.setHeader("Access-Control-Allow-Origin", origen);
  }
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  // Petición de comprobación previa (preflight) que envía el navegador.
  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  if (req.method !== "POST") {
    return res.status(405).json({ error: "Método no permitido" });
  }

  // 2. Validación. Las claves del JSON (nom, correu, telefon, text) son las que
  // envía el frontend; si se cambian allí, hay que cambiarlas también aquí.
  const {
    nom: nombre,
    correu: correo,
    telefon: telefono = "",
    text: mensaje,
  } = req.body ?? {};
  const campos = { nombre, correo, telefono, mensaje };

  if (!nombre || !correo || !mensaje) {
    return res.status(400).json({ error: "Faltan campos obligatorios" });
  }
  for (const [campo, valor] of Object.entries(campos)) {
    if (typeof valor !== "string" || valor.length > MAX_LONGITUD[campo]) {
      return res.status(400).json({ error: `Campo no válido: ${campo}` });
    }
  }
  if (!EMAIL_VALIDO.test(correo)) {
    return res.status(400).json({ error: "Correo no válido" });
  }

  // 3. Límite de peticiones. Se comprueba después de validar para que los
  // envíos mal formados no gasten el cupo de un visitante legítimo.
  const ip = (req.headers["x-forwarded-for"] ?? req.socket?.remoteAddress ?? "")
    .split(",")[0]
    .trim();
  if (!(await permitido(ip))) {
    return res.status(429).json({ error: "Demasiadas peticiones, inténtalo más tarde" });
  }

  // 4. Envío del correo.
  try {
    const { error } = await resend.emails.send({
      from: process.env.CONTACT_FROM,
      to: process.env.CONTACT_TO,
      subject: "Solicitud de contacto desde el portfolio",
      html: `<p><strong>Nombre:</strong> ${escaparHtml(nombre)}</p>
           <p><strong>Correo:</strong> ${escaparHtml(correo)}</p>
           <p><strong>Teléfono:</strong> ${escaparHtml(telefono)}</p>
           <p><strong>Mensaje:</strong> ${escaparHtml(mensaje).replace(/\n/g, "<br>")}</p>`,
    });
    // Resend no lanza excepción si falla: devuelve el error en la respuesta.
    if (error) throw error;

    return res.status(200).json({ success: true, message: "Mensaje enviado correctamente" });
  } catch (error) {
    console.error("Error de Resend:", error);
    return res.status(500).json({ error: "Error al enviar el correo" });
  }
}
