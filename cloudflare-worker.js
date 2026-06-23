export default {
  async fetch(request, env) {
    const token = env.BOT_TOKEN;
    if (!token) {
      return new Response(JSON.stringify({ error: "BOT_TOKEN missing" }), {
        status: 500, headers: { "Content-Type": "application/json" }
      });
    }

    const url = new URL(request.url);

    // Health check
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok" }), {
        headers: { "Content-Type": "application/json" }
      });
    }

    // Proxy POST /telegram-api/<method> -> api.telegram.org/bot<token>/<method>
    if (request.method === "POST" && url.pathname.startsWith("/telegram-api/")) {
      const parts = url.pathname.split("/");
      const method = parts[parts.length - 1];
      if (!method) {
        return new Response("Bad request", { status: 400 });
      }
      try {
        const body = await request.text();
        const resp = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: body
        });
        return new Response(await resp.text(), {
          status: resp.status,
          headers: { "Content-Type": "application/json" }
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500 });
      }
    }

    return new Response("Not found", { status: 404 });
  }
}
