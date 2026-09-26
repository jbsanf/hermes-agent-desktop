import http from 'node:http';

export async function startProvider() {
  const answer = 'FLATPAK_STREAMING_OK';
  const requests = [];
  const server = http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/v1/models') {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ object: 'list', data: [{ id: 'mock-model', object: 'model', owned_by: 'local-test' }] }));
      return;
    }
    if (req.method !== 'POST' || req.url !== '/v1/chat/completions') {
      res.writeHead(404).end();
      return;
    }
    let raw = '';
    req.on('data', chunk => { raw += chunk; });
    req.on('end', async () => {
      const body = JSON.parse(raw);
      requests.push(body);
      if (!body.stream) {
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify({ id: 'test', object: 'chat.completion', created: 0, model: 'mock-model',
          choices: [{ index: 0, message: { role: 'assistant', content: answer }, finish_reason: 'stop' }],
          usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 } }));
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      const chunk = (delta, finish = null) => `data: ${JSON.stringify({id:'test', object:'chat.completion.chunk', created:0,
        model:'mock-model', choices:[{index:0,delta,finish_reason:finish}]})}\n\n`;
      for (const content of ['FLATPAK_', 'STREAMING_', 'OK']) {
        res.write(chunk({ content }));
        await new Promise(resolve => setTimeout(resolve, 150));
      }
      res.write(chunk({}, 'stop'));
      res.end('data: [DONE]\n\n');
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { answer, requests, url: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }) };
}
