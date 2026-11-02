import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { buildSync } from 'esbuild';
import axios from 'axios';
import { configureStore } from '@reduxjs/toolkit';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Provider } from 'react-redux';

// Compile the actual client modules. All transports below are local doubles.
const storage = new Map();
globalThis.localStorage = {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: key => storage.delete(key),
};
globalThis.window = { location: { origin: 'http://localhost:3010', protocol: 'http:' } };
const built = buildSync({
  stdin: {
    resolveDir: fileURLToPath(new URL('../', import.meta.url)),
    contents: `
      export * from './src/services/apiService';
      export * from './src/lib/api-errors';
      export * from './src/lib/chat-payload';
      export * from './src/lib/websocket';
      export * from './src/store/slices/authSlice';
      export { default as authReducer } from './src/store/slices/authSlice';
      export { Chat } from './src/components/Chat';
      export { ChatMarkdown } from './src/components/ChatMarkdown';
      export { Button } from './src/components/ui/button';
      export { ToastProvider } from './src/components/ui/toast';
    `,
  },
  bundle: true, write: false, format: 'cjs', platform: 'node', jsx: 'automatic',
  external: ['react', 'react/*', 'react-dom/*', 'react-redux', '@reduxjs/toolkit', 'axios'],
  define: { 'import.meta.env.DEV': 'false' },
});
const compiled = { exports: {} };
new Function('require', 'module', 'exports', built.outputFiles[0].text)(createRequire(import.meta.url), compiled, compiled.exports);
const app = compiled.exports;

const user = { user_id: 'test-user', username: 'test-user', email: 'test@example.invalid' };
const token = { access_token: 'synthetic-test-token', token_type: 'bearer', expires_in: 3600, user_info: user };
const store = () => configureStore({ reducer: { auth: app.authReducer } });
const reply = data => { app.apiClient.defaults.adapter = async config => ({ data, status: 200, statusText: 'OK', headers: {}, config }); };
const fail = (status, data) => {
  app.apiClient.defaults.adapter = async config => {
    throw new axios.AxiosError('test transport failure', 'ERR_BAD_RESPONSE', config, null,
      { status, data, config, headers: {}, statusText: 'test' });
  };
};

test('HTTP errors retain status and business code through the API wrapper', async () => {
  fail(401, { code: 1004, message: 'invalid test token' });
  await assert.rejects(app.apiService.get('/test'), error =>
    error instanceof app.ApiError && error.status === 401 && error.code === 1004 && app.isAuthenticationError(error));
});

test('server failures are distinguishable from authentication failures', async () => {
  fail(500, { message: 'synthetic server failure' });
  await assert.rejects(app.apiService.get('/test'), error => error.status === 500 && !app.isAuthenticationError(error));
});

test('validation details become displayable text without echoing input', () => {
  assert.equal(app.responseErrorMessage({ detail: [{ msg: '字段错误', input: 'private-input' }, null] }), '字段错误');
  assert.equal(app.responseErrorMessage({ detail: { unexpected: true } }), undefined);
});

async function signedInStore() {
  reply({ success: true, data: token });
  const state = store();
  await state.dispatch(app.login({ username: user.username, password: 'synthetic' }));
  return state;
}

test('token refresh accepts the backend token envelope and updates stored credentials', async () => {
  const state = await signedInStore();
  const refreshed = { ...token, access_token: 'refreshed-test-token' };
  reply({ success: true, token: refreshed, user_info: user });
  const result = await state.dispatch(app.refreshToken());
  assert.equal(result.meta.requestStatus, 'fulfilled');
  assert.equal(state.getState().auth.token, refreshed.access_token);
  assert.equal(storage.get('auth_token'), refreshed.access_token);
});

test('temporary refresh failure preserves a session in its last five minutes', async () => {
  const state = await signedInStore();
  storage.set('auth_expires_at', String(Date.now() + 120_000));
  fail(503, { message: 'synthetic outage' });
  const refresh = state.dispatch(app.refreshToken());
  assert.equal(state.getState().auth.isLoading, false);
  await refresh;
  assert.equal(state.getState().auth.isAuthenticated, true);
  assert.equal(storage.get('auth_token'), token.access_token);
});

test('refresh rejection clears an invalid session from both Redux and storage', async () => {
  const state = await signedInStore();
  fail(401, { code: 1004 });
  await state.dispatch(app.refreshToken());
  assert.equal(state.getState().auth.isAuthenticated, false);
  assert.equal(storage.get('auth_token'), undefined);
});

test('a delayed refresh cannot sign the user back in after logout', async () => {
  const state = await signedInStore();
  const { promise, resolve } = Promise.withResolvers();
  app.apiClient.defaults.adapter = async config => {
    if (config.url.endsWith('/refresh')) await promise;
    return { data: { success: true, token }, status: 200, statusText: 'OK', headers: {}, config };
  };
  const refresh = state.dispatch(app.refreshToken());
  await state.dispatch(app.logout());
  resolve();
  await refresh;
  assert.equal(state.getState().auth.isAuthenticated, false);
  assert.equal(storage.get('auth_token'), undefined);
});

test('current-user lookup accepts user_info without an unsafe cast', async () => {
  reply({ success: true, user_info: user });
  const state = store();
  await state.dispatch(app.getCurrentUser());
  assert.equal(state.getState().auth.user.user_id, user.user_id);
});

test('temporary validation network failure preserves the signed-in state', async () => {
  const state = store();
  reply({ success: true, data: token });
  await state.dispatch(app.login({ username: 'test-user', password: 'synthetic' }));
  fail(503, { message: 'synthetic temporary outage' });
  await state.dispatch(app.validateToken());
  assert.equal(state.getState().auth.isAuthenticated, true);
  assert.equal(storage.get('auth_token'), token.access_token);
});

test('invalid-token validation clears the signed-in state', async () => {
  const state = store();
  reply({ success: true, data: token });
  await state.dispatch(app.login({ username: 'test-user', password: 'synthetic' }));
  fail(401, { code: 1004, message: 'synthetic expired token' });
  await state.dispatch(app.validateToken());
  assert.equal(state.getState().auth.isAuthenticated, false);
  assert.equal(storage.get('auth_token'), undefined);
});

test('malformed citation entries and non-text metadata cannot reach rendered source text', () => {
  const citations = app.readCitations([null, 12, { title: {} }, { title: '有效来源', url: {}, source_org: '测试来源' }]);
  assert.deepEqual(citations, [{ title: '有效来源', source_org: '测试来源' }]);
  assert.deepEqual(app.parseMessageMetadata('bad json'), {});
  assert.deepEqual(app.parseMessageMetadata('[1,2]'), {});
});

test('stream envelopes normalize timestamps, preserve citations, and ignore malformed rows', () => {
  const response = app.parseChatResponse({ type: 'completion', final_response: {
    messages: [null, { content: '测试响应', agent: 'Parser' }],
    events: [{ id: 'e1', type: 'tool_call', agent: 'Parser', content: 'parse', timestamp: 1700000000 }],
    citations: [{ title: '测试来源', url: 'https://example.invalid/source' }],
  } });
  assert.equal(response.final_response.events[0].timestamp.getUTCFullYear(), 2023);
  assert.equal(response.final_response.messages.length, 1);
  assert.equal(response.final_response.citations[0].title, '测试来源');
  assert.deepEqual(app.parseChatResponse(null), {});
});

test('chat source cards render safely with mixed valid and malformed metadata', () => {
  const message = { id: 'test', type: 'ai', content: '测试回答', agent: 'Parser', timestamp: new Date(),
    metadata: { citations: [null, { title: {} }, { title: '有效来源', url: 'javascript:alert(1)', source_org: '测试来源' }] } };
  const html = renderToStaticMarkup(React.createElement(Provider, { store: store() },
    React.createElement(app.ToastProvider, null, React.createElement(app.Chat, { messages: [message], onSendMessage() {} }))));
  assert.match(html, /有效来源/);
  assert.doesNotMatch(html, /href="javascript:/);
});

test('Button asChild composes an anchor instead of nesting it inside a button', () => {
  const html = renderToStaticMarkup(React.createElement(app.Button, { asChild: true },
    React.createElement('a', { href: '/test' }, '测试链接')));
  assert.match(html, /^<a /);
  assert.doesNotMatch(html, /<button/);
});

test('markdown keeps table and link rendering after removing unused node props', () => {
  const html = renderToStaticMarkup(React.createElement(app.ChatMarkdown, {
    content: '| 字段 | 值 |\n| --- | --- |\n| 姓名 | 虚构样例 |\n\n[来源](https://example.invalid)',
  }));
  assert.match(html, /<table/);
  assert.match(html, /虚构样例/);
  assert.match(html, /rel="noopener noreferrer"/);
});

class FakeSocket {
  static OPEN = 1;
  static instances = [];
  readyState = 0;
  sent = [];
  constructor(url) { this.url = url; FakeSocket.instances.push(this); }
  open() { this.readyState = 1; this.onopen?.({}); }
  close(code = 1000) { this.readyState = 3; this.onclose?.({ code }); }
  send(value) { this.sent.push(JSON.parse(value)); }
  receive(value) { this.onmessage?.({ data: JSON.stringify(value) }); }
}
globalThis.WebSocket = FakeSocket;
const latestSocket = () => FakeSocket.instances.at(-1);

test('concurrent connect calls share one connection and retain same-origin proxy routing', async () => {
  const service = new app.WebSocketService('user-a', 'name', undefined, 'synthetic');
  const before = FakeSocket.instances.length;
  const first = service.connect();
  const second = service.connect();
  assert.equal(first, second);
  assert.equal(FakeSocket.instances.length, before + 1);
  assert.equal(new URL(latestSocket().url).host, 'localhost:3010');
  latestSocket().open(); await first;
  service.disconnect();
});

test('disconnect cancels an opening connection and ignores its late callbacks', async () => {
  const service = new app.WebSocketService('user-a');
  const pending = service.connect();
  const old = latestSocket();
  const rejected = assert.rejects(pending, /取消/);
  service.disconnect(); await rejected;
  const next = service.connect();
  const current = latestSocket(); current.open(); await next;
  old.open(); old.close(1006);
  assert.equal(service.status, 'connected');
  service.disconnect();
});

test('refreshed credentials replace the old global socket service', () => {
  const first = app.createWebSocketService('user-a', 'name', undefined, 'old-test-token');
  assert.equal(app.createWebSocketService('user-a', 'name', undefined, 'old-test-token'), first);
  const refreshed = app.createWebSocketService('user-a', 'name', undefined, 'new-test-token');
  assert.notEqual(refreshed, first);
  refreshed.disconnect();
});

test('subscription cleanup removes callbacks and AI errors reach the error listener', async () => {
  const service = new app.WebSocketService('user-a');
  let connected = 0;
  let error = '';
  const handler = () => { connected += 1; };
  service.on('connected', handler);
  service.on('connected', handler);
  service.on('ai_error', payload => { error = payload.error; });
  const pending = service.connect(); const socket = latestSocket(); socket.open(); await pending;
  socket.receive({ type: 'connect', content: { connection_id: 'c1' } });
  assert.equal(connected, 1);
  service.off('connected', handler);
  socket.receive({ type: 'connect', content: { connection_id: 'c2' } });
  socket.receive({ type: 'ai_error', content: { error: 'synthetic tool failure' } });
  assert.equal(connected, 1);
  assert.equal(error, 'synthetic tool failure');
  service.disconnect();
});

test('sending records the selected conversation and refuses disconnected sends', async () => {
  const service = new app.WebSocketService('user-a');
  assert.equal(service.sendChatMessage('offline'), false);
  const pending = service.connect(); const socket = latestSocket(); socket.open(); await pending;
  service.setConversationId('conversation-a');
  assert.equal(service.sendChatMessage('synthetic message', 'medical'), true);
  assert.equal(socket.sent[0].metadata.conversation_id, 'conversation-a');
  assert.equal(socket.sent[0].metadata.mode, 'medical');
  service.disconnect();
});

test('server internal failure permits retry instead of being labeled an authentication error', async () => {
  const service = new app.WebSocketService('user-a');
  let authErrors = 0;
  service.on('auth_error', () => { authErrors += 1; });
  const pending = service.connect(); const socket = latestSocket(); socket.open(); await pending;
  socket.close(1011);
  assert.equal(authErrors, 0);
  assert.equal(service.status, 'disconnected');
  service.disconnect(); // Cancel the scheduled retry; no real network or wait.
});

test('repeated backend initialization failures stop after five reconnect attempts', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const service = new app.WebSocketService('user-a');
  const pending = service.connect();
  latestSocket().open(); await pending;
  latestSocket().close(1011);
  const before = FakeSocket.instances.length;
  for (let retry = 0; retry < 5; retry += 1) {
    t.mock.timers.tick(30000);
    latestSocket().open();
    latestSocket().close(1011);
  }
  t.mock.timers.tick(60000);
  assert.equal(FakeSocket.instances.length, before + 5);
  service.disconnect();
});
