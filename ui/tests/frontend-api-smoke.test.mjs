import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { buildSync } from 'esbuild';

const baseURL = process.env.AIDE_SMOKE_BASE_URL;

test('frontend client contracts against the local preview API', { skip: !baseURL }, async t => {
  const target = new URL(baseURL);
  assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname), 'Use a loopback preview server');
  assert.equal(target.protocol, 'http:');
  const username = process.env.AIDE_SMOKE_USERNAME;
  const password = process.env.AIDE_SMOKE_PASSWORD;
  assert.ok(username && password, 'Set AIDE_SMOKE_USERNAME and AIDE_SMOKE_PASSWORD');

  // In-memory browser storage only. No browser, real browser cookies, or model calls.
  const storage = new Map();
  globalThis.localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  };
  globalThis.window = { location: { origin: target.origin, protocol: target.protocol } };
  const output = buildSync({
    stdin: { resolveDir: fileURLToPath(new URL('../', import.meta.url)), contents: `
      export * from './src/services/apiService';
      export * from './src/services/medicalDocumentAPI';
      export * from './src/lib/api-errors';
      export { WebSocketService } from './src/lib/websocket';
      export { AuthManager } from './src/lib/auth';
    ` },
    bundle: true, write: false, platform: 'node', format: 'cjs', packages: 'external',
    define: { 'import.meta.env.DEV': 'false' },
  });
  const compiled = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(createRequire(import.meta.url), compiled, compiled.exports);
  const api = compiled.exports;
  api.apiClient.defaults.baseURL = target.origin;
  api.apiClient.defaults.proxy = false;
  api.apiClient.defaults.maxRedirects = 0;
  api.apiClient.defaults.timeout = 15000;
  // Keep responses, request headers and credentials out of test failure output.
  t.mock.method(console, 'log', () => {});
  t.mock.method(console, 'warn', () => {});
  t.mock.method(console, 'error', () => {});
  async function request(operation) {
    try { return await operation(); }
    catch (error) { throw new Error(`API request failed (HTTP ${api.toApiError(error).status ?? 'unavailable'})`); }
  }
  async function statusOf(operation) {
    try { await operation(); return 200; }
    catch (error) { return api.toApiError(error).status; }
  }
  let userId;
  await t.test('login returns a usable token envelope', async () => {
    const response = await request(() => api.authAPI.login({ username, password }));
    assert.equal(response.success, true);
    assert.equal(typeof response.data?.access_token, 'string');
    assert.equal(typeof response.data?.user_info?.user_id, 'string');
    userId = response.data.user_info.user_id;
    api.AuthManager.saveAuth(response.data);
  });
  assert.ok(userId, 'Login must succeed before data checks');

  await t.test('current user matches the authenticated identity', async () => {
    const response = await request(() => api.authAPI.getCurrentUser());
    assert.equal(response.success, true);
    assert.equal(response.user_info?.user_id, userId);
  });
  await t.test('refresh normalizes the backend token field into data', async () => {
    const response = await request(() => api.authAPI.refreshToken());
    assert.equal(response.success, true);
    assert.equal(typeof response.data?.access_token, 'string');
    assert.equal(response.data?.user_info?.user_id, userId);
    api.AuthManager.saveAuth(response.data);
    const current = await request(() => api.authAPI.getCurrentUser());
    assert.equal(current.user_info?.user_id, userId);
  });
  await t.test('notes and tags expose their nested list envelopes', async () => {
    const [notes, tags] = await request(() => Promise.all([api.noteAPI.getNotes(userId), api.noteAPI.getTags(userId)]));
    assert.equal(notes.success, true); assert.equal(tags.success, true);
    assert.ok(Array.isArray(notes.data?.data)); assert.ok(Array.isArray(tags.data?.data));
    assert.ok(tags.data.data.every(tag => typeof tag === 'string'));
    assert.ok(notes.data.data.every(note => String(note.user_id) === userId));
  });
  await t.test('todos and statistics expose the expected separate response shapes', async () => {
    const [todos, stats] = await request(() => Promise.all([api.todoAPI.getTodos(userId), api.todoAPI.getStats(userId)]));
    assert.equal(todos.success, true); assert.ok(Array.isArray(todos.data));
    assert.equal(stats.success, true); assert.equal(typeof stats.data?.data?.total, 'number');
    assert.ok(todos.data.every(todo => String(todo.user_id) === userId));
  });
  await t.test('health calendar records include counts and ownership', async () => {
    const response = await request(() => api.healthRecordAPI.getRecords(userId));
    assert.equal(response.success, true);
    assert.ok(Array.isArray(response.data?.records));
    assert.ok(api.isRecord(response.data?.daily_counts));
    assert.equal(typeof response.data.total, 'number');
    assert.ok(response.data.records.every(record => String(record.user_id) === userId));
  });
  await t.test('conversation list uses stable public IDs', async () => {
    const response = await request(() => api.conversationAPI.getConversations(userId));
    assert.equal(response.success, true); assert.ok(Array.isArray(response.data));
    assert.ok(response.data.every(row => typeof row.id_str === 'string' && String(row.user_id) === userId));
  });
  await t.test('saved medical documents reopen with source and field data', async subtest => {
    const list = await request(() => api.medicalDocumentAPI.list());
    assert.ok(Array.isArray(list));
    if (!list.length) { subtest.skip('No saved document in this preview database'); return; }
    const document = await request(() => api.medicalDocumentAPI.get(list[0].id));
    assert.equal(document.id, list[0].id);
    assert.ok(Array.isArray(document.result?.source_lines));
    assert.ok(api.isRecord(document.result?.fields));
  });
  await t.test('empty parsing requests fail validation before a model call', async () => {
    assert.equal(await statusOf(() => api.medicalDocumentAPI.parseText('')), 422);
  });
  await t.test('chat receives the server welcome through the frontend proxy', {
    skip: process.env.AIDE_SMOKE_WS === '1' ? false : 'Set AIDE_SMOKE_WS=1 with the local MCP service running',
  }, async () => {
    const socket = new api.WebSocketService(userId, username, undefined, api.AuthManager.getToken());
    const welcome = Promise.withResolvers();
    socket.on('connected', welcome.resolve);
    const timer = setTimeout(() => welcome.reject(new Error('No WebSocket welcome within 30 seconds')), 30_000);
    try {
      const [, message] = await Promise.all([socket.connect(), welcome.promise]);
      assert.ok(message.connection_id);
    } finally {
      clearTimeout(timer);
      socket.disconnect();
    }
  });
  await t.test('invalid credentials cannot read medical documents', async () => {
    api.AuthManager.clearAuth();
    assert.equal(await statusOf(() => api.apiClient.get('/api/medical-documents', {
      headers: { Authorization: 'Bearer invalid-local-smoke-token' },
    })), 401);
  });
});
