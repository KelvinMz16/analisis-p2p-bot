addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  const url = new URL(request.url);

  if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
    return new Response(JSON.stringify({ status: "ok", service: "Bot Proxy" }), {
      headers: { "Content-Type": "application/json" }
    });
  }

  if (request.method === "POST" && url.pathname.startsWith("/telegram-api/")) {
    const method = url.pathname.replace("/telegram-api/", "");
    try {
      const body = await request.text();
      const resp = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body
      });
      return new Response(await resp.text(), {
        status: resp.status,
        headers: { "Content-Type": "application/json" }
      });
    } catch (e) {
      return new Response(JSON.stringify({ ok: false, error: e.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      });
    }
  }

  // Proxy for Binance API (bypasses HF IP block / 451)
  if (url.pathname.startsWith("/binance-api/")) {
    const restPath = url.pathname.replace("/binance-api/", "");
    const query = url.search;
    const targetUrl = `https://api.binance.com/${restPath}${query}`;
    try {
      const resp = await fetch(targetUrl, {
        method: request.method,
        headers: { "User-Agent": "Mozilla/5.0" }
      });
      return new Response(await resp.text(), {
        status: resp.status,
        headers: { "Content-Type": "application/json" }
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      });
    }
  }

  // Proxy for Jupiter API (HF DNS no resuelve quote-api.jup.ag)
  if (url.pathname.startsWith("/jupiter-api/")) {
    const restPath = url.pathname.replace("/jupiter-api/", "");
    const query = url.search;
    const targetUrl = `https://quote-api.jup.ag/${restPath}${query}`;
    try {
      const resp = await fetch(targetUrl, {
        method: request.method,
        headers: { "User-Agent": "Mozilla/5.0" }
      });
      return new Response(await resp.text(), {
        status: resp.status,
        headers: { "Content-Type": "application/json" }
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      });
    }
  }

  return new Response("Not found", { status: 404 });
}
