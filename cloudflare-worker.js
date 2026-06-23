export default {
  async fetch(request) {
    const url = new URL(request.url);
    const telegramUrl = `https://api.telegram.org${url.pathname}${url.search}`;

    const response = await fetch(telegramUrl, {
      method: request.method,
      headers: request.headers,
      body: request.body
    });

    return response;
  }
}
