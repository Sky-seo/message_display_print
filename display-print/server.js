const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const ROOT_DIR = __dirname;
const INPUTS_PATH = path.join(ROOT_DIR, 'inputs.json');
const LOG_PATH = path.join(ROOT_DIR, 'log.json');
const MAX_INPUT_ITEMS = 100;

function ensureInputsFile() {
  if (!fs.existsSync(INPUTS_PATH)) {
    fs.writeFileSync(INPUTS_PATH, '[]\n', 'utf8');
  }
}

function ensureLogFile() {
  if (!fs.existsSync(LOG_PATH)) {
    fs.writeFileSync(LOG_PATH, '[]\n', 'utf8');
  }
}

function readInputs() {
  ensureInputsFile();
  const raw = fs.readFileSync(INPUTS_PATH, 'utf8').trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed) ? parsed.slice(-MAX_INPUT_ITEMS) : [];
}

function writeInputs(inputs) {
  fs.writeFileSync(INPUTS_PATH, `${JSON.stringify(inputs, null, 2)}\n`, 'utf8');
}

function readLog() {
  ensureLogFile();
  const raw = fs.readFileSync(LOG_PATH, 'utf8').trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed) ? parsed : [];
}

function writeLog(entries) {
  fs.writeFileSync(LOG_PATH, `${JSON.stringify(entries, null, 2)}\n`, 'utf8');
}

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(payload));
}

function sendFile(res, filePath) {
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
      return;
    }

    const ext = path.extname(filePath);
    const mimeByExt = {
      '.html': 'text/html; charset=utf-8',
      '.css': 'text/css; charset=utf-8',
      '.js': 'application/javascript; charset=utf-8',
      '.json': 'application/json; charset=utf-8'
    };
    const mime = mimeByExt[ext] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': mime });
    res.end(data);
  });
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        reject(new Error('Request too large'));
      }
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

function createEntryId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'POST' && req.url === '/api/inputs') {
    try {
      const rawBody = await parseBody(req);
      const parsed = JSON.parse(rawBody || '{}');
      const value = typeof parsed.value === 'string' ? parsed.value.trim() : '';
      if (!value) {
        sendJson(res, 400, { ok: false, error: 'value is required' });
        return;
      }

      const inputs = readInputs();
      const log = readLog();
      const entry = {
        id: createEntryId(),
        value,
        createdAt: new Date().toISOString()
      };

      log.push(entry);
      writeLog(log);

      inputs.push({
        id: entry.id,
        value,
        createdAt: entry.createdAt
      });
      writeInputs(inputs.slice(-MAX_INPUT_ITEMS));
      sendJson(res, 200, { ok: true });
      return;
    } catch (error) {
      sendJson(res, 400, { ok: false, error: 'invalid request body' });
      return;
    }
  }

  if (req.method === 'GET' && req.url === '/api/inputs') {
    try {
      sendJson(res, 200, readInputs());
    } catch (error) {
      sendJson(res, 500, { ok: false, error: 'failed to read inputs' });
    }
    return;
  }

  let requestPath = req.url === '/' ? '/index.html' : req.url;
  requestPath = requestPath.split('?')[0];
  const safePath = path.normalize(requestPath).replace(/^(\.\.[/\\])+/, '');
  const filePath = path.join(ROOT_DIR, safePath);

  if (!filePath.startsWith(ROOT_DIR)) {
    res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Forbidden');
    return;
  }

  sendFile(res, filePath);
});

server.listen(PORT, () => {
  ensureInputsFile();
  ensureLogFile();
  writeInputs(readInputs());
  console.log(`Server running: http://localhost:${PORT}`);
});
