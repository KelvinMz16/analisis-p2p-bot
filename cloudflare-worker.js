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

  return new Response("Not found", { status: 404 });
}
