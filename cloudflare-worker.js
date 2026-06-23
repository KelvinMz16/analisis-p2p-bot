export default {
  async fetch(request, env) {
    const BOT_TOKEN = env.BOT_TOKEN;
    const TELEGRAM_API = `https://api.telegram.org/bot${BOT_TOKEN}`;
    const url = new URL(request.url);

    // Health check
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return new Response(JSON.stringify({ status: "ok", service: "Bot Proxy" }), {
        headers: { "Content-Type": "application/json" }
      });
    }

    // Telegram API Proxy — POST only, PTB y requests compatibles
    if (request.method === "POST" && url.pathname.startsWith("/telegram-api/")) {
      const afterPrefix = url.pathname.replace("/telegram-api/", "");
      const parts = afterPrefix.split("/").filter(Boolean);
      const method = parts.length >= 2 ? parts[1] : parts[0];
      if (!method || method.includes("/")) {
        return new Response(JSON.stringify({ ok: false, error: "Invalid method" }), {
          status: 400, headers: { "Content-Type": "application/json" }
        });
      }
      try {
        const contentType = request.headers.get("Content-Type") || "application/json";
        if (contentType.includes("multipart/form-data")) {
          const formData = await request.formData();
          const upstreamForm = new FormData();
          for (const [key, value] of formData.entries()) {
            upstreamForm.append(key, value);
          }
          const resp = await fetch(`${TELEGRAM_API}/${method}`, {
            method: "POST", body: upstreamForm
          });
          const data = await resp.text();
          return new Response(data, {
            status: resp.status,
            headers: { "Content-Type": "application/json" }
          });
        } else {
          const body = await request.text();
          const resp = await fetch(`${TELEGRAM_API}/${method}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: body
          });
          const data = await resp.text();
          return new Response(data, {
            status: resp.status,
            headers: { "Content-Type": "application/json" }
          });
        }
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: e.message }), {
          status: 500,
          headers: { "Content-Type": "application/json" }
        });
      }
    }

    // Generic POST proxy
    if (request.method === "POST" && url.pathname === "/proxy") {
      const targetUrl = url.searchParams.get("url");
      if (!targetUrl) {
        return new Response(JSON.stringify({ ok: false, error: "Missing ?url=" }), {
          status: 400, headers: { "Content-Type": "application/json" }
        });
      }
      try {
        const incomingContentType = request.headers.get("Content-Type") || "application/json";
        const upstreamHeaders = { "Content-Type": incomingContentType };
        const authHeader = request.headers.get("Authorization");
        if (authHeader) upstreamHeaders["Authorization"] = authHeader;

        if (incomingContentType.includes("multipart/form-data")) {
          const formData = await request.formData();
          const upstreamForm = new FormData();
          for (const [key, value] of formData.entries()) {
            upstreamForm.append(key, value);
          }
          const resp = await fetch(targetUrl, {
            method: "POST", body: upstreamForm
          });
          const data = await resp.text();
          return new Response(data, {
            status: resp.status,
            headers: { "Content-Type": "application/json" }
          });
        } else {
          const body = await request.text();
          const resp = await fetch(targetUrl, {
            method: "POST",
            headers: upstreamHeaders,
            body: body
          });
          const data = await resp.text();
          return new Response(data, {
            status: resp.status,
            headers: { "Content-Type": "application/json" }
          });
        }
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: e.message }), {
          status: 500, headers: { "Content-Type": "application/json" }
        });
      }
    }

    // Generic GET proxy
    if (request.method === "GET" && url.pathname === "/proxy-get") {
      const targetUrl = url.searchParams.get("url");
      if (!targetUrl) {
        return new Response(JSON.stringify({ ok: false, error: "Missing ?url=" }), {
          status: 400, headers: { "Content-Type": "application/json" }
        });
      }
      try {
        const authHeader = request.headers.get("Authorization");
        const upstreamHeaders = {};
        if (authHeader) upstreamHeaders["Authorization"] = authHeader;
        const resp = await fetch(targetUrl, { headers: upstreamHeaders });
        const data = await resp.text();
        return new Response(data, {
          status: resp.status,
          headers: { "Content-Type": "application/json" }
        });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: e.message }), {
          status: 500, headers: { "Content-Type": "application/json" }
        });
      }
    }

    return new Response("Not found", { status: 404 });
  }
};
