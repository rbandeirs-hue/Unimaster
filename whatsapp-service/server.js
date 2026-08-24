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

function s(id) { return sessions[id] || (sessions[id] = { sock: null, status: 'disconnected', qr: null, qrDataUrl: null, number: null, queue: [], sending: false, starting: false, enviadas: new Map() }); }

// Últimas mensagens enviadas, por instância.
//
// Quando o aparelho do destinatário não consegue decifrar uma mensagem (troca
// de aparelho, sessão dessincronizada, iPhone com o app fechado há muito tempo),
// ele devolve um "retry receipt" pedindo o reenvio. O Baileys atende esse pedido
// chamando `getMessage(key)`; sem isso ele usa o padrão, que devolve `undefined`,
// registra "recv retry request, but message not available" e NÃO reenvia — e a
// conversa fica presa em "Aguardando mensagem" para sempre.
const MSG_CACHE_MAX = 300;
const MSG_TTL_MS = 7 * 24 * 60 * 60 * 1000;   // além disso o retry não vem mais

// O cache também vai para o disco. Só a memória não bastava: se o destinatário
// estiver com o aparelho desligado, o pedido de reenvio só chega quando ele
// voltar — horas ou dias depois — e um reinício do serviço no meio perderia a
// mensagem. Guardado por instância, dentro da pasta de sessão, que já é
// privada e já é apagada no logout.
function arquivoMensagens(id) {
  return path.join(AUTH_DIR, String(id), 'mensagens.json');
}

// Só texto é persistido. Mídia carrega Buffer, que não sobrevive a
// JSON.stringify/parse e voltaria corrompida na hora de reenviar; para esse
// caso o cache em memória continua valendo enquanto o processo viver.
function ehTexto(conteudo) {
  const chaves = Object.keys(conteudo || {}).filter((k) => conteudo[k] != null);
  if (!chaves.length) return false;
  return chaves.every((k) => k === 'conversation' || k === 'extendedTextMessage' || k === 'messageContextInfo');
}

function gravarMensagens(id) {
  const alvo = arquivoMensagens(id);
  const tmp = alvo + '.tmp';
  try {
    const st = s(id);
    const agora = Date.now();
    const obj = {};
    for (const [msgId, reg] of st.enviadas || []) {
      if (reg && reg.disco && (agora - reg.t) < MSG_TTL_MS) obj[msgId] = { t: reg.t, m: reg.m };
    }
    // tmp + rename: um kill no meio da escrita deixaria o JSON truncado, e a
    // instância subiria sem histórico nenhum.
    fs.writeFileSync(tmp, JSON.stringify(obj), { mode: 0o600 });
    fs.renameSync(tmp, alvo);
  } catch (e) {
    try { fs.rmSync(tmp, { force: true }); } catch (e2) {}
    logger.warn({ id, err: String(e) }, 'nao foi possivel gravar o historico de reenvio');
  }
}

function carregarMensagens(id) {
  const st = s(id);
  if (!st.enviadas) st.enviadas = new Map();
  if (st.carregado) return;
  st.carregado = true;
  try {
    const obj = JSON.parse(fs.readFileSync(arquivoMensagens(id), 'utf8'));
    const agora = Date.now();
    let n = 0;
    for (const [msgId, reg] of Object.entries(obj || {})) {
      if (!reg || !reg.m || !reg.t) continue;
      if (agora - reg.t >= MSG_TTL_MS) continue;      // vencido: não volta
      st.enviadas.set(msgId, { t: reg.t, m: reg.m, disco: true });
      n++;
    }
    if (n) logger.warn({ id, n }, 'historico de reenvio recuperado do disco');
  } catch (e) {
    // Ausente no primeiro uso, ou ilegível por uma queda antiga: começar vazio
    // é melhor do que impedir a sessão de subir.
  }
}

function lembrarMensagem(id, msgId, conteudo) {
  if (!msgId || !conteudo) return;
  const st = s(id);
  if (!st.enviadas) st.enviadas = new Map();
  const disco = ehTexto(conteudo);
  st.enviadas.set(msgId, { t: Date.now(), m: conteudo, disco });
  // Map preserva a ordem de inserção: descartar a primeira chave é descartar a
  // mensagem mais antiga.
  while (st.enviadas.size > MSG_CACHE_MAX) {
    st.enviadas.delete(st.enviadas.keys().next().value);
  }
  if (disco) gravarMensagens(id);
}

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
    carregarMensagens(id);
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
      // Responde ao pedido de reenvio do destinatário (ver lembrarMensagem).
      getMessage: async (key) => {
        const st = s(id);
        const reg = st.enviadas && st.enviadas.get(key.id);
        const guardada = reg && reg.m;
        if (!guardada) {
          logger.warn({ id, msgId: key.id }, 'pedido de reenvio sem a mensagem em cache');
          return undefined;
        }
        logger.warn({ id, msgId: key.id }, 'reenviando mensagem a pedido do destinatario');
        return guardada;
      },
    });
    st.sock = sock;
    st.status = 'connecting';

    sock.ev.on('creds.update', saveCreds);
    // Mensagens mandadas do próprio aparelho também podem receber pedido de
    // reenvio; sem guardá-las o buraco continuaria aberto pelo outro lado.
    sock.ev.on('messages.upsert', (ev) => {
      for (const m of (ev && ev.messages) || []) {
        if (m && m.key && m.key.fromMe && m.key.id && m.message) lembrarMensagem(id, m.key.id, m.message);
      }
    });
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
      const enviada = await st.sock.sendMessage(jid, { text: job.mensagem });
      if (enviada && enviada.key && enviada.key.id) lembrarMensagem(id, enviada.key.id, enviada.message);
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
  // `cache` é o tamanho do histórico de reenvio: se ficar em 0 depois de enviar,
  // o pedido de reenvio do destinatário não teria como ser atendido.
  res.json({
    status: st.status, number: st.number, fila: st.queue.length,
    cache: (st.enviadas && st.enviadas.size) || 0,
  });
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
  // O histórico de reenvio é da sessão que acabou de sair: some junto, senão
  // sobraria em memória e o `carregado` impediria a leitura da sessão nova.
  st.enviadas = new Map(); st.carregado = false;
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
