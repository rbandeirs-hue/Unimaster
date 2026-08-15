/**
 * Unimaster WhatsApp — microserviço Baileys multi-instância.
 * Uma sessão (número) por academia, identificada por :id (academia_id).
 * Sem Chromium, sem Docker, sem banco. Sessões salvas em ./auth/<id>.
 *
 * Endpoints (todos exigem header x-api-key):
 *   POST /instances/:id/connect   -> inicia/garante a sessão; devolve status (+ qr se precisar parear)
 *   GET  /instances/:id/qr        -> { status, qr }  (qr = dataURL PNG ou null)
 *   GET  /instances/:id/status    -> { status, number }
 *   POST /instances/:id/send      -> body { telefone, mensagem } -> enfileira o envio
 *   POST /instances/:id/logout    -> desconecta e limpa a sessão
 *   GET  /health                  -> ok
 */
const fs = require('fs');
const path = require('path');
const express = require('express');
const pino = require('pino');
const QR = require('qrcode');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');

const PORT = parseInt(process.env.WPP_PORT || '3333', 10);
const HOST = process.env.WPP_HOST || '127.0.0.1';
const AUTH_DIR = path.join(__dirname, 'auth');
const SEND_DELAY_MS = parseInt(process.env.WPP_SEND_DELAY_MS || '4000', 10); // intervalo entre mensagens

// API key compartilhada com o Flask (arquivo ou env)
function loadApiKey() {
  if (process.env.WPP_API_KEY) return process.env.WPP_API_KEY.trim();
  try { return fs.readFileSync(path.join(__dirname, 'api_key.txt'), 'utf8').trim(); }
  catch (e) { return ''; }
}
const API_KEY = loadApiKey();

const logger = pino({ level: process.env.WPP_LOG_LEVEL || 'warn' });
const sessions = {}; // id -> { sock, status, qr, qrDataUrl, number, queue, sending, starting }

function s(id) { return sessions[id] || (sessions[id] = { sock: null, status: 'disconnected', qr: null, qrDataUrl: null, number: null, queue: [], sending: false, starting: false }); }

function normalizePhone(raw) {
  let d = String(raw || '').replace(/\D/g, '');
  if (!d) return null;
  if (d.startsWith('00')) d = d.slice(2);
  if (!d.startsWith('55')) d = '55' + d;        // assume Brasil
  return d;
}

async function startSession(id) {
  const st = s(id);
  if (st.starting || (st.sock && (st.status === 'open' || st.status === 'connecting' || st.status === 'qr'))) return st;
  st.starting = true;
  try {
    const dir = path.join(AUTH_DIR, String(id));
    fs.mkdirSync(dir, { recursive: true });
    const { state, saveCreds } = await useMultiFileAuthState(dir);
    let version;
    try { ({ version } = await fetchLatestBaileysVersion()); } catch (e) { version = undefined; }

    const sock = makeWASocket({
      version,
      auth: state,
      printQRInTerminal: false,
      logger,
      browser: ['Unimaster', 'Chrome', '1.0'],
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });
    st.sock = sock;
    st.status = 'connecting';

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', async (u) => {
      const { connection, lastDisconnect, qr } = u;
      if (qr) {
        st.qr = qr;
        st.status = 'qr';
        try { st.qrDataUrl = await QR.toDataURL(qr, { margin: 1, width: 300 }); } catch (e) { st.qrDataUrl = null; }
      }
      if (connection === 'open') {
        st.status = 'open';
        st.qr = null; st.qrDataUrl = null;
        try { st.number = (sock.user && sock.user.id || '').split(':')[0] || null; } catch (e) {}
        processQueue(id);
      }
      if (connection === 'close') {
        const code = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output && lastDisconnect.error.output.statusCode;
        if (code === DisconnectReason.loggedOut) {
          st.status = 'logged_out';
          st.sock = null; st.qr = null; st.qrDataUrl = null; st.number = null;
        } else {
          // 515 (restart required, após escanear o QR) e demais quedas: reconecta.
          // IMPORTANTE: zerar o sock e o starting para o guard de startSession não bloquear.
          st.sock = null;
          st.starting = false;
          st.status = 'connecting';
          setTimeout(() => startSession(id).catch(() => {}), 1500); // reconecta
        }
      }
    });
  } catch (e) {
    logger.error({ id, err: String(e) }, 'startSession falhou');
    s(id).status = 'error';
  } finally {
    s(id).starting = false;
  }
  return s(id);
}

async function processQueue(id) {
  const st = s(id);
  if (st.sending) return;
  if (st.status !== 'open' || !st.sock) return;
  st.sending = true;
  while (st.queue.length && st.status === 'open' && st.sock) {
    const job = st.queue.shift();
    try {
      const phone = normalizePhone(job.telefone);
      if (!phone) { job.reject && job.reject('telefone inválido'); continue; }
      // resolve o JID correto (trata 9º dígito do Brasil)
      let jid = phone + '@s.whatsapp.net';
      try {
        const res = await st.sock.onWhatsApp(phone);
        if (res && res[0] && res[0].exists && res[0].jid) jid = res[0].jid;
      } catch (e) {}
      await st.sock.sendMessage(jid, { text: job.mensagem });
      job.resolve && job.resolve(jid);
    } catch (e) {
      logger.warn({ id, err: String(e) }, 'falha ao enviar');
      job.reject && job.reject(String(e));
    }
    if (st.queue.length) await new Promise((r) => setTimeout(r, SEND_DELAY_MS));
  }
  st.sending = false;
}

// ---------------- HTTP ----------------
const app = express();
app.use(express.json({ limit: '256kb' }));

app.get('/health', (req, res) => res.json({ ok: true }));

app.use((req, res, next) => {
  if (!API_KEY) return res.status(500).json({ error: 'API key não configurada no serviço' });
  if ((req.header('x-api-key') || '') !== API_KEY) return res.status(401).json({ error: 'não autorizado' });
  next();
});

app.post('/instances/:id/connect', async (req, res) => {
  const id = req.params.id;
  await startSession(id);
  const st = s(id);
  res.json({ status: st.status, qr: st.qrDataUrl, number: st.number });
});

app.get('/instances/:id/qr', (req, res) => {
  const st = s(req.params.id);
  res.json({ status: st.status, qr: st.qrDataUrl, number: st.number });
});

app.get('/instances/:id/status', (req, res) => {
  const st = s(req.params.id);
  res.json({ status: st.status, number: st.number, fila: st.queue.length });
});

app.post('/instances/:id/send', async (req, res) => {
  const id = req.params.id;
  const { telefone, mensagem } = req.body || {};
  if (!telefone || !mensagem) return res.status(400).json({ error: 'telefone e mensagem são obrigatórios' });
  const st = s(id);
  if (st.status !== 'open') {
    // tenta levantar a sessão (se já pareada antes, reconecta sozinho)
    if (st.status === 'disconnected' || st.status === 'logged_out') startSession(id).catch(() => {});
    return res.status(409).json({ error: 'instância não conectada', status: st.status });
  }
  st.queue.push({ telefone, mensagem });
  processQueue(id);
  res.json({ queued: true, fila: st.queue.length });
});

app.post('/instances/:id/logout', async (req, res) => {
  const id = req.params.id;
  const st = s(id);
  try { if (st.sock) await st.sock.logout(); } catch (e) {}
  st.sock = null; st.status = 'disconnected'; st.qr = null; st.qrDataUrl = null; st.number = null; st.queue = [];
  try { fs.rmSync(path.join(AUTH_DIR, String(id)), { recursive: true, force: true }); } catch (e) {}
  res.json({ ok: true });
});

// Reconecta sessões já pareadas ao subir o serviço
function bootstrapExisting() {
  try {
    const ids = fs.readdirSync(AUTH_DIR, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);
    ids.forEach((id) => startSession(id).catch(() => {}));
    if (ids.length) logger.warn({ ids }, 'reconectando sessões existentes');
  } catch (e) {}
}

app.listen(PORT, HOST, () => {
  logger.warn(`Unimaster WhatsApp ouvindo em http://${HOST}:${PORT}`);
  bootstrapExisting();
});
