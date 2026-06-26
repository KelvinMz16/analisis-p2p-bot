addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url)
  const path = url.pathname

  // Telegram API proxy
  if (path.startsWith('/telegram-api/')) {
    const method = path.split('/telegram-api/')[1]
    const apiUrl = `https://api.telegram.org/bot${BOT_TOKEN}/${method}`
    const body = await request.text()
    const resp = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body || undefined,
    })
    const result = await resp.json()
    return new Response(JSON.stringify(result), {
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    })
  }

  // Binance API proxy
  if (path.startsWith('/binance-api/')) {
    const subpath = path.split('/binance-api/')[1]
    const apiUrl = `https://api.binance.com/${subpath}${url.search}`
    const resp = await fetch(apiUrl, {
      method: request.method,
      headers: { 'User-Agent': 'Mozilla/5.0' },
      body: request.method === 'POST' ? await request.text() : undefined,
    })
    const result = await resp.text()
    return new Response(result, {
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    })
  }

  // Bybit API proxy (backup)
  if (path.startsWith('/bybit-api/')) {
    const subpath = path.split('/bybit-api/')[1]
    const apiUrl = `https://api.bybit.com/${subpath}${url.search}`
    const resp = await fetch(apiUrl, {
      method: request.method,
      headers: { 'User-Agent': 'Mozilla/5.0' },
      body: request.method === 'POST' ? await request.text() : undefined,
    })
    const result = await resp.text()
    return new Response(result, {
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    })
  }

  // Health check
  return new Response('OK', { headers: { 'Content-Type': 'text/plain' } })
}
