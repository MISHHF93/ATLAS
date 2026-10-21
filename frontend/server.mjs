// A single TCP listener. FastAPI runs over the child's stdio, never on another port.
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { createRequire } from "node:module";
import next from "next";

const require = createRequire(import.meta.url);
const { WebSocketServer } = require("next/dist/compiled/ws");
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "..");
const python = process.env.ATLAS_PYTHON ?? path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const child = spawn(python, ["-B", "-u", path.join(directory, "scripts/asgi_stdio.py")], {
  cwd: root, stdio: ["pipe", "pipe", "inherit"], windowsHide: true,
  env: { ...process.env, PYTHONPATH: path.join(root, "src") },
});
const channels = new Map();
let sequence = 0;
let available = true;
function send(message) {
  if (!available || child.stdin.destroyed) throw new Error("Backend unavailable");
  if (child.stdin.writableLength > 4 * 1024 * 1024) throw new Error("Backend overloaded");
  child.stdin.write(JSON.stringify(message) + "\n");
}
createInterface({ input: child.stdout }).on("line", (line) => {
  try {
    const message = JSON.parse(line);
    channels.get(message.id)?.(message);
  } catch (error) { console.error("Invalid backend response:", error.message); }
});
child.on("error", (error) => { console.error(error); available = false; });
child.on("exit", () => {
  available = false;
  for (const callback of channels.values()) callback({ type: "bridge.error" });
  channels.clear();
});

const app = next({ dev: !process.argv.includes("--production"), dir: directory });
await app.prepare();
const handle = app.getRequestHandler();
const server = http.createServer(async (req, res) => {
  if (!req.url?.startsWith("/api/")) return handle(req, res);
  if (!available) { res.writeHead(503).end("Backend unavailable"); return; }
  const id = String(++sequence);
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 1024 * 1024) { res.writeHead(413).end(); return; }
    chunks.push(chunk);
  }
  const timeout = setTimeout(() => {
    channels.delete(id);
    if (!res.headersSent) res.writeHead(504);
    res.end("Backend timeout");
    try { send({ id, type: "cancel" }); } catch {}
  }, 60_000);
  channels.set(id, (message) => {
    if (message.type === "http.response.start") res.writeHead(message.status, message.headers.flat());
    if (message.type === "http.response.body") {
      res.write(Buffer.from(message.body ?? "", "base64"));
      if (!message.more_body) { clearTimeout(timeout); channels.delete(id); res.end(); }
    }
    if (message.type === "bridge.error") {
      clearTimeout(timeout); channels.delete(id);
      if (!res.headersSent) res.writeHead(503);
      res.end("Backend unavailable");
    }
  });
  try {
    send({ id, type: "http", url: req.url, method: req.method, headers: req.headers, body: Buffer.concat(chunks).toString("base64") });
  } catch {
    clearTimeout(timeout); channels.delete(id); res.writeHead(503).end("Backend unavailable");
  }
});
const sockets = new WebSocketServer({ noServer: true, maxPayload: 64 * 1024 });
server.on("upgrade", (req, socket, head) => {
  if (!req.url?.startsWith("/ws/market-stream")) { app.getUpgradeHandler()(req, socket, head); return; }
  if (!available) { socket.destroy(); return; }
  sockets.handleUpgrade(req, socket, head, (ws) => {
    const id = String(++sequence);
    channels.set(id, (message) => {
      if (message.type === "websocket.send" && ws.readyState === 1) {
        if (ws.bufferedAmount > 1024 * 1024) { ws.close(1013, "Slow consumer"); return; }
        ws.send(message.text ?? Buffer.from(message.bytes ?? "", "base64"));
      }
      if (message.type === "websocket.close" || message.type === "bridge.error") ws.close(1011);
    });
    ws.on("message", (data) => {
      try { send({ id, type: "websocket.receive", text: data.toString() }); }
      catch { ws.close(1013); }
    });
    ws.on("close", () => {
      channels.delete(id);
      try { send({ id, type: "websocket.disconnect", code: 1000 }); } catch {}
    });
    send({ id, type: "websocket", url: req.url, headers: req.headers });
  });
});
server.on("error", (error) => { console.error(error); child.kill(); process.exitCode = 1; });
server.listen(3000, "127.0.0.1", () => console.log("ATLAS http://localhost:3000 (HTTP + WebSocket; Python over stdio)"));
function shutdown() { for (const ws of sockets.clients) ws.terminate(); child.kill(); server.close(); }
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
